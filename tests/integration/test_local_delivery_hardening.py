import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import respx
from httpx import ConnectTimeout, Response
from sqlalchemy import func, select
from tests.integration import test_worker_delivery as worker_tests

from src.api.v1.routers import ingest
from src.core.exceptions import ConflictError, ForbiddenError
from src.domain.entities.subscription import Subscription
from src.domain.enums import DeliveryStatus
from src.infrastructure.db.models import DeliveryAttemptModel, EndpointModel
from src.infrastructure.db.repositories.delivery_attempt_repository import (
    PostgresDeliveryAttemptRepository,
)
from src.infrastructure.db.repositories.subscription_repository import (
    PostgresSubscriptionRepository,
)
from src.infrastructure.queue.tasks import deliver_webhook as worker
from src.services.delivery_service import DeliveryService

worker_delivery = worker_tests.worker_delivery


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_concurrent_admission_keeps_one_event_and_fanout(worker_delivery):
    from src.domain.entities.webhook_event import WebhookEvent
    from src.infrastructure.db.base import async_session_maker
    from src.infrastructure.db.models import WebhookEventModel
    from src.infrastructure.db.repositories.webhook_event_repository import (
        PostgresWebhookEventRepository,
    )

    factory, _, existing_id, endpoint_id = worker_delivery
    with factory() as session:
        source_id = session.get(WebhookEventModel, existing_id).source_id
    key = str(uuid4())
    now = datetime.now(UTC)

    async def admit():
        async with async_session_maker() as session:
            return await PostgresWebhookEventRepository(session).create_admission(
                WebhookEvent(
                    id=uuid4(),
                    created_at=now,
                    updated_at=now,
                    source_id=source_id,
                    payload={"safe": True},
                    headers={},
                    idempotency_key=key,
                    event_type="test",
                    received_at=now,
                ),
                [endpoint_id],
            )

    first, second = await asyncio.gather(admit(), admit())
    assert first[0].id == second[0].id
    assert sorted([first[1], second[1]]) == [False, True]
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(DeliveryAttemptModel)
                .where(DeliveryAttemptModel.event_id == first[0].id)
            )
            == 1
        )


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_fanout_failure_rolls_back_event(worker_delivery):
    from sqlalchemy.exc import IntegrityError

    from src.domain.entities.webhook_event import WebhookEvent
    from src.infrastructure.db.base import async_session_maker
    from src.infrastructure.db.models import WebhookEventModel
    from src.infrastructure.db.repositories.webhook_event_repository import (
        PostgresWebhookEventRepository,
    )

    factory, _, existing_id, _ = worker_delivery
    with factory() as session:
        source_id = session.get(WebhookEventModel, existing_id).source_id
    now, new_id = datetime.now(UTC), uuid4()
    with pytest.raises(IntegrityError):
        async with async_session_maker() as session:
            await PostgresWebhookEventRepository(session).create_admission(
                WebhookEvent(
                    id=new_id,
                    created_at=now,
                    updated_at=now,
                    source_id=source_id,
                    payload={},
                    headers={},
                    idempotency_key=None,
                    event_type=None,
                    received_at=now,
                ),
                [uuid4()],
            )
    with factory() as session:
        assert session.get(WebhookEventModel, new_id) is None


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_concurrent_manual_retry_has_one_successor(worker_delivery):
    from src.infrastructure.db.base import async_session_maker

    factory, delivery_id, event_id, _ = worker_delivery
    with factory() as session:
        session.get(DeliveryAttemptModel, delivery_id).status = DeliveryStatus.FAILED
        session.commit()

    async def retry():
        async with async_session_maker() as session:
            return await PostgresDeliveryAttemptRepository(session).schedule_retry(
                delivery_id, 2
            )

    first, second = await asyncio.gather(retry(), retry())
    assert first.id == second.id
    with factory() as session:
        original = session.get(DeliveryAttemptModel, delivery_id)
        assert original.status == DeliveryStatus.EXHAUSTED
        assert original.next_attempt_at is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(DeliveryAttemptModel)
                .where(DeliveryAttemptModel.event_id == event_id)
            )
            == 2
        )


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("delivered", DeliveryStatus.SUCCESS),
        ("not_delivered", DeliveryStatus.EXHAUSTED),
    ],
)
@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_stale_claim_resolution_is_owned_audited_and_never_resends(
    worker_delivery, outcome, status
):
    from src.infrastructure.db.base import async_session_maker

    factory, delivery_id, event_id, endpoint_id = worker_delivery
    claim = datetime.now(UTC) - timedelta(seconds=120)
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        row.status, row.attempted_at = DeliveryStatus.DELIVERING, claim
        owner = session.get(EndpointModel, endpoint_id).owner_id
        session.commit()
    async with async_session_maker() as session:
        repo = PostgresDeliveryAttemptRepository(session)
        with pytest.raises(ForbiddenError):
            await repo.resolve_claim(delivery_id, uuid4(), claim, outcome, "ticket-1")
        await session.rollback()
        with pytest.raises(ConflictError):
            await repo.resolve_claim(
                delivery_id, owner, claim + timedelta(seconds=1), outcome, "ticket-1"
            )
        await session.rollback()
        resolved = await repo.resolve_claim(
            delivery_id, owner, claim, outcome, "ticket-1"
        )
        assert resolved.status == status and resolved.resolved_by == owner
        assert (
            resolved.resolution_reference == "ticket-1"
            and resolved.resolved_at is not None
        )
    with respx.mock as boundary:
        result = worker.deliver_webhook.run(
            str(delivery_id), str(event_id), str(endpoint_id)
        )
        assert result["status"] == str(status)
        assert not boundary.calls


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_recent_claim_cannot_be_resolved(worker_delivery):
    from src.infrastructure.db.base import async_session_maker

    factory, delivery_id, _, endpoint_id = worker_delivery
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        row.status = DeliveryStatus.DELIVERING
        claim = row.attempted_at
        owner = session.get(EndpointModel, endpoint_id).owner_id
        session.commit()
    async with async_session_maker() as session:
        with pytest.raises(ConflictError):
            await PostgresDeliveryAttemptRepository(session).resolve_claim(
                delivery_id, owner, claim, "not_delivered", "ticket-1"
            )


@pytest.mark.parametrize(
    "outcome,status",
    [
        ("delivered", DeliveryStatus.SUCCESS),
        ("not_delivered", DeliveryStatus.EXHAUSTED),
    ],
)
@pytest.mark.parametrize("late_result", ["success", "connect_timeout"])
@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_operator_resolution_survives_late_worker_result(
    worker_delivery, monkeypatch, outcome, status, late_result
):
    from src.infrastructure.db.base import async_session_maker

    factory, delivery_id, event_id, endpoint_id = worker_delivery
    claim = datetime.now(UTC) - timedelta(seconds=120)

    class StaleClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return claim.astimezone(tz) if tz else claim.replace(tzinfo=None)

    monkeypatch.setattr(worker, "datetime", StaleClock)
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        row.next_attempt_at = row.next_dispatch_at = claim
        endpoint = session.get(EndpointModel, endpoint_id)
        endpoint.failure_count = 3
        owner = endpoint.owner_id
        session.commit()
    entered, release, resumed = Event(), Event(), Event()

    def receiver(request):
        entered.set()
        assert release.wait(10), "Operator resolution did not release the receiver"
        resumed.set()
        if late_result == "connect_timeout":
            raise ConnectTimeout("Controlled late timeout")
        return Response(200, text="late result")

    with respx.mock as boundary, ThreadPoolExecutor(max_workers=1) as executor:
        route = boundary.post("https://93.184.216.34/hook").mock(side_effect=receiver)
        task = asyncio.wrap_future(
            executor.submit(
                worker.deliver_webhook.run,
                str(delivery_id),
                str(event_id),
                str(endpoint_id),
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            with factory() as session:
                row = session.get(DeliveryAttemptModel, delivery_id)
                assert row.status == DeliveryStatus.DELIVERING
                assert row.attempted_at == claim
            async with async_session_maker() as session:
                resolved = await asyncio.wait_for(
                    PostgresDeliveryAttemptRepository(session).resolve_claim(
                        delivery_id, owner, claim, outcome, "ticket-late"
                    ),
                    5,
                )
            assert resolved.status == status and not task.done()
        finally:
            release.set()
            result = await asyncio.wait_for(asyncio.shield(task), 10)
        assert resumed.is_set(), "Receiver timed out instead of returning a late result"
        assert result == {"status": str(status), "response_code": None}
        assert route.call_count == 1
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        assert row.status == status and row.attempted_at == claim
        assert row.resolved_by == owner and row.resolved_at == resolved.resolved_at
        assert row.updated_at == resolved.updated_at
        assert row.resolution == outcome and row.resolution_reference == "ticket-late"
        assert row.error_message == "Operator confirmed " + outcome
        assert row.response_code is None and row.response_body is None
        assert row.next_attempt_at is None and row.next_dispatch_at is None
        assert row.attempt_number == 1
        assert session.get(EndpointModel, endpoint_id).failure_count == 3
    worker.enqueue_delivery.assert_not_called()


@pytest.mark.parametrize("failure", ["read_timeout", "soft_timeout"])
def test_read_timeout_remains_ambiguous_without_retry(worker_delivery, failure):
    from billiard.exceptions import SoftTimeLimitExceeded
    from httpx import ReadTimeout

    factory, delivery_id, event_id, endpoint_id = worker_delivery
    with respx.mock as boundary:
        target = boundary.post("https://93.184.216.34/hook").mock(
            side_effect=(
                ReadTimeout("controlled")
                if failure == "read_timeout"
                else SoftTimeLimitExceeded()
            )
        )
        args = [str(delivery_id), str(event_id), str(endpoint_id)]
        assert worker.deliver_webhook.run(*args)["status"] == "delivering"
        assert worker.deliver_webhook.run(*args)["status"] == "delivering"
        assert target.call_count == 1
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        assert row.attempt_number == 1 and row.next_dispatch_at is None


def test_redirect_is_not_followed_and_private_target_never_called(worker_delivery):
    _, delivery_id, event_id, endpoint_id = worker_delivery
    with respx.mock as boundary:
        target = boundary.post("https://93.184.216.34/hook").mock(
            return_value=Response(
                302, headers={"Location": "http://169.254.169.254/metadata"}
            )
        )
        assert (
            worker.deliver_webhook.run(
                str(delivery_id), str(event_id), str(endpoint_id)
            )["status"]
            == "failed"
        )
        assert len(boundary.calls) == target.call_count == 1


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_endpoint_configuration_preserves_newer_failure_counter(worker_delivery):
    from src.infrastructure.db.base import async_session_maker
    from src.infrastructure.db.repositories.endpoint_repository import (
        PostgresEndpointRepository,
    )

    factory, _, _, endpoint_id = worker_delivery
    async with async_session_maker() as session:
        repo = PostgresEndpointRepository(session)
        stale = await repo.get_by_id(endpoint_id)
        with factory() as other:
            other.get(EndpointModel, endpoint_id).failure_count = 8
            other.commit()
        stale.name = "Changed name"
        updated = await repo.update(stale)
        assert updated.failure_count == 8 and updated.name == "Changed name"
        assert (await repo.update_failure_count(endpoint_id)).failure_count == 9
        assert (
            await repo.update_failure_count(endpoint_id, reset=True)
        ).failure_count == 0


async def test_unsafe_url_validation_does_not_echo_credentials(client, auth_headers):
    response = await client.post(
        "/api/v1/endpoints",
        headers=auth_headers,
        json={
            "name": "unsafe",
            "url": "http://user:synthetic-secret@example.com/hook",
        },
    )
    assert response.status_code == 422
    assert "synthetic-secret" not in response.text


def test_host_sni_and_fixed_ip_survive_http_transport(worker_delivery, monkeypatch):
    import socket

    factory, delivery_id, event_id, endpoint_id = worker_delivery
    with factory() as session:
        session.get(EndpointModel, endpoint_id).url = "https://receiver.example/hook"
        session.commit()
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ],
    )
    original = worker.httpx.Client
    client_options = []

    def create_client(*args, **kwargs):
        client_options.append(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(worker.httpx, "Client", create_client)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    with respx.mock as boundary:
        target = boundary.post("https://93.184.216.34/hook").mock(
            return_value=Response(200)
        )
        assert (
            worker.deliver_webhook.run(
                str(delivery_id), str(event_id), str(endpoint_id)
            )["status"]
            == "success"
        )
        request = target.calls[0].request
        assert request.headers["Host"] == "receiver.example"
        assert request.extensions["sni_hostname"] == "receiver.example"
        assert request.headers["X-Delivery-ID"] == str(delivery_id)
        assert client_options[0]["trust_env"] is False
        assert client_options[0]["follow_redirects"] is False


@pytest.mark.parametrize(
    "flag",
    ["PLATFORM_BOTS_ENABLED", "PLATFORM_TELEGRAM_ENABLED", "TELEGRAM_REPLIES_ENABLED"],
)
async def test_platform_mode_rejects_legacy_and_global_metrics(
    client, monkeypatch, flag
):
    from src.core.config import settings

    monkeypatch.setattr(settings, flag, True)
    assert (
        await client.get("/api/v1/endpoints", params={"owner_id": str(uuid4())})
    ).status_code == 503
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"email": "synthetic@example.com", "password": "unused"},
        )
    ).status_code == 503
    assert (
        await client.post("/webhooks/ingest/any-source", json={})
    ).status_code == 503
    assert (await client.get("/metrics")).status_code == 503
    assert (await client.get("/health/live")).status_code == 200


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
def test_failure_metadata_and_counters_commit_before_advisory_redis(
    worker_delivery, monkeypatch
):
    from sqlalchemy import text

    factory, delivery_id, event_id, endpoint_id = worker_delivery

    def cache_failure(*args, **kwargs):
        with factory() as session:
            session.execute(text("SET LOCAL lock_timeout='100ms'"))
            row = session.get(EndpointModel, endpoint_id, with_for_update=True)
            assert row.failure_count == 1
            delivery = session.get(DeliveryAttemptModel, delivery_id)
            assert delivery.status == DeliveryStatus.FAILED
            assert delivery.response_code == 500
        return 1

    monkeypatch.setattr(worker.SyncCircuitBreaker, "record_failure", cache_failure)
    with respx.mock as boundary:
        boundary.post("https://93.184.216.34/hook").mock(
            return_value=Response(500, text="Controlled receiver failure")
        )
        result = worker.deliver_webhook.run(
            str(delivery_id), str(event_id), str(endpoint_id)
        )
        assert result["response_code"] == 500
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        assert (
            row.response_code == 500
            and row.response_body == "Controlled receiver failure"
        )


def test_compressed_response_never_expands_preview(worker_delivery, monkeypatch):
    import gzip

    from httpx._decoders import GZipDecoder

    _, delivery_id, event_id, endpoint_id = worker_delivery
    monkeypatch.setattr(
        GZipDecoder,
        "decode",
        lambda *args: pytest.fail("Untrusted preview decompressed"),
    )
    body = gzip.compress(b"x" * (8 * 1024 * 1024))
    from httpx import ByteStream, MockTransport

    original = worker.httpx.Client
    transport = MockTransport(
        lambda request: Response(
            500,
            stream=ByteStream(body),
            headers={"Content-Encoding": "gzip"},
        )
    )
    monkeypatch.setattr(
        worker.httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs)
    )
    with transport:
        assert (
            worker.deliver_webhook.run(
                str(delivery_id), str(event_id), str(endpoint_id)
            )["response_code"]
            == 500
        )


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_accepted_ingest_has_intents_before_background_dispatch(
    worker_delivery, client, db_session, monkeypatch
):
    factory, _, event_id, endpoint_id = worker_delivery
    from src.infrastructure.db.models import SourceModel, WebhookEventModel

    with factory() as session:
        event = session.get(WebhookEventModel, event_id)
        source = session.get(SourceModel, event.source_id)
        source_id, owner_id, slug = source.id, source.owner_id, source.slug
    now = datetime.now(UTC)
    await PostgresSubscriptionRepository(db_session).create(
        Subscription(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            source_id=source_id,
            owner_id=owner_id,
            endpoint_id=endpoint_id,
            event_type_filter=["*"],
        )
    )
    monkeypatch.setattr(ingest, "_dispatch_deliveries", AsyncMock())
    response = await client.post(
        f"/webhooks/ingest/{slug}",
        json={"accepted": True},
        headers={"X-Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202
    from uuid import UUID

    saved_id = UUID(response.json()["event_id"])
    attempts = await PostgresDeliveryAttemptRepository(db_session).get_by_event(
        saved_id, None, 100
    )
    assert len(attempts) == 1
    assert attempts[0].status == DeliveryStatus.PENDING


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
def test_two_concurrent_failures_both_increment_endpoint(worker_delivery):
    factory, delivery_id, event_id, endpoint_id = worker_delivery
    now = datetime.now(UTC)
    second_id = uuid4()
    with factory() as session:
        session.add(
            DeliveryAttemptModel(
                id=second_id,
                event_id=event_id,
                endpoint_id=endpoint_id,
                status=DeliveryStatus.PENDING,
                attempt_number=1,
                attempted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    ready = Barrier(2, timeout=5)

    def receiver(request):
        ready.wait()
        return Response(500)

    with respx.mock as boundary, ThreadPoolExecutor(max_workers=2) as executor:
        boundary.post("https://93.184.216.34/hook").mock(side_effect=receiver)
        futures = [
            executor.submit(
                worker.deliver_webhook.run, str(item), str(event_id), str(endpoint_id)
            )
            for item in (delivery_id, second_id)
        ]
        assert all(item.result(timeout=8)["status"] == "failed" for item in futures)
    with factory() as session:
        assert session.get(EndpointModel, endpoint_id).failure_count == 2


@pytest.mark.parametrize(
    "status",
    [
        DeliveryStatus.DELIVERING,
        DeliveryStatus.SUCCESS,
        DeliveryStatus.PENDING,
        DeliveryStatus.RETRYING,
    ],
)
@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_manual_retry_rejects_active_or_successful_delivery(
    worker_delivery, db_session, status
):
    factory, delivery_id, event_id, _ = worker_delivery
    with factory() as session:
        session.get(DeliveryAttemptModel, delivery_id).status = status
        session.commit()
    repo = PostgresDeliveryAttemptRepository(db_session)
    with pytest.raises(ConflictError):
        await DeliveryService(repo, None).schedule_retry(delivery_id, 2)
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(DeliveryAttemptModel)
            .where(DeliveryAttemptModel.event_id == event_id)
        )
        == 1
    )
