import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event
from time import perf_counter
from unittest.mock import Mock
from uuid import uuid4

import pytest
import respx
from httpx import Response
from kombu.exceptions import OperationalError
from scripts import recover_legacy_deliveries as scanner
from sqlalchemy import select
from tests.integration import test_worker_delivery as worker_tests

from src.domain.entities.subscription import Subscription
from src.domain.enums import DeliveryStatus
from src.infrastructure.db.base import async_session_maker
from src.infrastructure.db.mappers import webhook_event_to_entity
from src.infrastructure.db.models import (
    DeliveryAttemptModel,
    EndpointModel,
    WebhookEventModel,
)
from src.infrastructure.db.repositories.delivery_attempt_repository import (
    PostgresDeliveryAttemptRepository,
)
from src.infrastructure.queue import dispatcher
from src.infrastructure.queue.celery_app import celery_app
from src.infrastructure.queue.delivery_publication import enqueue_delivery
from src.infrastructure.queue.tasks import deliver_webhook as task_module
from src.services.delivery_service import DeliveryService

worker_delivery = worker_tests.worker_delivery


@pytest.fixture
def recovery_delivery(worker_delivery, monkeypatch):
    factory, *identities = worker_delivery
    monkeypatch.setattr(scanner, "sync_session_maker", factory)
    return factory, *identities


def make_due(factory, delivery_id, *, publication_only=False):
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        past = datetime.now(UTC) - timedelta(seconds=1)
        if not publication_only:
            row.next_attempt_at = past
        row.next_dispatch_at = past
        session.commit()


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_initial_publication_failure_preserves_all_intents(
    worker_delivery, db_session, monkeypatch
):
    factory, _, event_id, endpoint_id = worker_delivery
    with factory() as session:
        event = webhook_event_to_entity(session.get(WebhookEventModel, event_id))
        owner_id = session.get(EndpointModel, endpoint_id).owner_id
    now = datetime.now(UTC)
    subscriptions = [
        Subscription(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            endpoint_id=endpoint_id,
            source_id=event.source_id,
            owner_id=owner_id,
        )
        for _ in range(2)
    ]
    unavailable = Mock(side_effect=OperationalError("synthetic publication outage"))
    monkeypatch.setattr(dispatcher, "enqueue_delivery", unavailable)
    assert await dispatcher.dispatch_event_deliveries(event, subscriptions) == []
    attempts = await PostgresDeliveryAttemptRepository(db_session).get_by_event(
        event_id, None, 100
    )
    assert len(attempts) == 3
    assert all(attempt.attempt_number == 1 for attempt in attempts)


def test_retry_publication_failure_keeps_durable_retry(worker_delivery, monkeypatch):
    factory, delivery_id, event_id, endpoint_id = worker_delivery
    unavailable = Mock(side_effect=OperationalError("synthetic retry outage"))
    monkeypatch.setattr(task_module, "enqueue_delivery", unavailable)
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook").mock(
            return_value=Response(500)
        )
        result = task_module.deliver_webhook.run(
            str(delivery_id), str(event_id), str(endpoint_id)
        )
        assert result["status"] == "failed"
        assert request.call_count == 1
    with factory() as session:
        delivery = session.get(DeliveryAttemptModel, delivery_id)
        assert delivery.attempt_number == 2
        assert delivery.status == DeliveryStatus.FAILED
        assert delivery.next_attempt_at > delivery.updated_at
        assert delivery.next_dispatch_at == delivery.next_attempt_at
    unavailable.assert_called_once_with(
        str(delivery_id), str(event_id), str(endpoint_id), countdown=10
    )


def test_retry_outage_recovery_replay_and_early_notification(
    recovery_delivery, monkeypatch
):
    factory, delivery_id, event_id, endpoint_id = recovery_delivery
    args = [str(delivery_id), str(event_id), str(endpoint_id)]
    monkeypatch.setattr(
        task_module,
        "enqueue_delivery",
        Mock(side_effect=OperationalError("synthetic notification outage")),
    )
    submitted = Mock(return_value="queued")
    monkeypatch.setattr(scanner, "enqueue_delivery", submitted)
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook").mock(
            side_effect=[Response(500), Response(200)]
        )
        assert task_module.deliver_webhook.run(*args)["status"] == "failed"
        assert task_module.deliver_webhook.run(*args)["status"] == "failed"
        assert request.call_count == 1
        assert scanner.scan_once() == 0
        make_due(factory, delivery_id)
        assert scanner.scan_once() == 1
        assert scanner.scan_once() == 0
        submitted.assert_called_once_with(*args)
        assert task_module.deliver_webhook.run(*args)["status"] == "success"
        assert task_module.deliver_webhook.run(*args)["status"] == "success"
        assert request.call_count == 2
        make_due(factory, delivery_id)
        assert scanner.scan_once() == 0


@pytest.mark.parametrize("outage", [False, True])
def test_scanner_lease_recovers_lost_publication(
    recovery_delivery, monkeypatch, outage
):
    factory, delivery_id, _, _ = recovery_delivery
    submitted = Mock(
        return_value="queued",
        side_effect=OperationalError("synthetic publication outage")
        if outage
        else None,
    )
    monkeypatch.setattr(scanner, "enqueue_delivery", submitted)
    assert scanner.scan_once() == (0 if outage else 1)
    assert scanner.scan_once() == 0
    with factory() as session:
        row = session.get(DeliveryAttemptModel, delivery_id)
        assert row.status == DeliveryStatus.PENDING
        assert row.attempt_number == 1
        assert row.next_dispatch_at > datetime.now(UTC) + timedelta(seconds=50)
    make_due(factory, delivery_id, publication_only=True)
    submitted.side_effect = None
    assert scanner.scan_once() == 1
    assert submitted.call_count == 2


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
def test_concurrent_scanners_publish_one_notification(recovery_delivery, monkeypatch):
    factory, delivery_id, event_id, endpoint_id = recovery_delivery
    ready = Barrier(2, timeout=5)
    original = scanner.claim_due_deliveries

    def race(session, batch_size):
        ready.wait()
        return original(session, batch_size)

    monkeypatch.setattr(scanner, "claim_due_deliveries", race)
    submitted = Mock(return_value="queued")
    monkeypatch.setattr(scanner, "enqueue_delivery", submitted)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = [workers.submit(scanner.scan_once) for _ in range(2)]
        assert sorted(result.result(timeout=5) for result in results) == [0, 1]
    submitted.assert_called_once_with(str(delivery_id), str(event_id), str(endpoint_id))
    with factory() as session:
        assert session.get(DeliveryAttemptModel, delivery_id).attempt_number == 1


@pytest.mark.parametrize(
    "status",
    [DeliveryStatus.SUCCESS, DeliveryStatus.DELIVERING, DeliveryStatus.EXHAUSTED],
)
def test_scanner_never_resends_terminal_or_active_claim(
    recovery_delivery, monkeypatch, status
):
    factory, delivery_id, _, _ = recovery_delivery
    with factory() as session:
        session.get(DeliveryAttemptModel, delivery_id).status = status
        session.commit()
    submitted = Mock()
    monkeypatch.setattr(scanner, "enqueue_delivery", submitted)
    assert scanner.scan_once() == 0
    submitted.assert_not_called()


def test_scanner_batch_is_bounded_and_progresses(recovery_delivery, monkeypatch):
    factory, _, event_id, endpoint_id = recovery_delivery
    now = datetime.now(UTC)
    with factory() as session:
        session.add_all(
            [
                DeliveryAttemptModel(
                    id=uuid4(),
                    event_id=event_id,
                    endpoint_id=endpoint_id,
                    attempt_number=1,
                    status=DeliveryStatus.PENDING,
                    attempted_at=now,
                    next_attempt_at=now,
                    next_dispatch_at=now,
                )
                for _ in range(104)
            ]
        )
        session.commit()
    submitted = Mock(return_value="queued")
    monkeypatch.setattr(scanner, "enqueue_delivery", submitted)
    assert scanner.scan_once() == 100
    assert scanner.scan_once() == 5
    assert scanner.scan_once() == 0
    assert len({call.args[0] for call in submitted.call_args_list}) == 105


@pytest.mark.parametrize("batch_size", [0, -1, 101])
def test_invalid_batch_rejected(recovery_delivery, batch_size):
    with pytest.raises(ValueError, match="batch size"):
        scanner.scan_once(batch_size)


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_manual_retry_persists_due_time_and_recovers(
    recovery_delivery, monkeypatch
):
    factory, delivery_id, event_id, endpoint_id = recovery_delivery
    with factory() as session:
        session.get(DeliveryAttemptModel, delivery_id).status = DeliveryStatus.SUCCESS
        session.commit()
    async with async_session_maker() as session:
        repo = PostgresDeliveryAttemptRepository(session)
        await DeliveryService(repo, Mock()).schedule_retry(delivery_id, 2)
        rows = (
            await session.scalars(
                select(DeliveryAttemptModel).where(
                    DeliveryAttemptModel.event_id == event_id,
                    DeliveryAttemptModel.status == DeliveryStatus.RETRYING,
                )
            )
        ).all()
        (row,) = rows
        assert row.attempt_number == 2
        assert row.next_attempt_at == row.attempted_at == row.next_dispatch_at
        assert row.next_attempt_at > row.created_at
        retry_id = row.id
    submitted = Mock(return_value="queued")
    monkeypatch.setattr(scanner, "enqueue_delivery", submitted)
    assert scanner.scan_once() == 0
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook").mock(
            return_value=Response(200)
        )
        args = [str(retry_id), str(event_id), str(endpoint_id)]
        assert task_module.deliver_webhook.run(*args)["status"] == "retrying"
        assert not request.calls
        make_due(factory, retry_id)
        assert scanner.scan_once() == 1
        submitted.assert_called_once_with(*args)
        assert task_module.deliver_webhook.run(*args)["status"] == "success"
        assert request.call_count == 1


def test_broker_wait_is_bounded_and_transport_retries_disabled(monkeypatch):
    original = celery_app.conf.broker_url
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://127.0.0.1:1/0")
    celery_app.conf.broker_url = "redis://127.0.0.1:1/0"
    started = perf_counter()
    try:
        with pytest.raises(OperationalError):
            enqueue_delivery(str(uuid4()), str(uuid4()), str(uuid4()))
    finally:
        celery_app.conf.broker_url = original
    assert perf_counter() - started < 5


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
def test_scanner_skips_a_locked_delivery_without_waiting(
    recovery_delivery, monkeypatch
):
    factory, delivery_id, _, _ = recovery_delivery
    submitted = Mock()
    monkeypatch.setattr(scanner, "enqueue_delivery", submitted)
    with factory() as session, ThreadPoolExecutor(max_workers=1) as workers:
        session.get(DeliveryAttemptModel, delivery_id, with_for_update=True)
        result = workers.submit(scanner.scan_once)
        try:
            assert result.result(timeout=2) == 0
        finally:
            session.rollback()
    submitted.assert_not_called()


def test_publication_uses_bounded_connection_and_uuid_arguments(monkeypatch):
    submitted = Mock(return_value=Mock(id="queued-notification"))
    monkeypatch.setattr(celery_app, "send_task", submitted)
    args = [str(uuid4()), str(uuid4()), str(uuid4())]
    assert enqueue_delivery(*args, countdown=10) == "queued-notification"
    call = submitted.call_args
    assert call.args == ("deliver_webhook",)
    assert call.kwargs["args"] == args
    assert call.kwargs["countdown"] == 10
    assert call.kwargs["retry"] is False
    options = call.kwargs["connection"].transport_options
    assert options["socket_connect_timeout"] == options["socket_timeout"] == 2
    assert options["retry_on_timeout"] is False


@pytest.mark.parametrize("worker_delivery", [True], indirect=True)
async def test_initial_publication_keeps_event_loop_responsive(
    worker_delivery, db_session, monkeypatch
):
    factory, _, event_id, endpoint_id = worker_delivery
    with factory() as session:
        event = webhook_event_to_entity(session.get(WebhookEventModel, event_id))
        owner_id = session.get(EndpointModel, endpoint_id).owner_id
    now = datetime.now(UTC)
    sub = Subscription(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        endpoint_id=endpoint_id,
        source_id=event.source_id,
        owner_id=owner_id,
    )
    release = Event()
    loop = asyncio.get_running_loop()

    def publish(*args):
        loop.call_soon_threadsafe(release.set)
        assert release.wait(1), "Publisher blocked the API event loop"
        return "queued"

    monkeypatch.setattr(dispatcher, "enqueue_delivery", publish)
    assert await dispatcher.dispatch_event_deliveries(event, [sub]) == ["queued"]
