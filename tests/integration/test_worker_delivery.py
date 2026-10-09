from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import uuid4

import pytest
import redis
import respx
from httpx import ConnectTimeout, Response
from sqlalchemy.orm import sessionmaker

from src.domain.enums import DeliveryStatus
from src.infrastructure.db.base import sync_engine
from src.infrastructure.db.models import (
    DeliveryAttemptModel,
    EndpointModel,
    SourceModel,
    UserModel,
    WebhookEventModel,
)
from src.infrastructure.queue.tasks import deliver_webhook as task_module


@pytest.fixture
def worker_delivery(monkeypatch):
    with sync_engine.connect() as connection:
        transaction = connection.begin()
        factory = sessionmaker(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        monkeypatch.setattr(task_module, "sync_session_maker", factory)
        with factory() as session:
            now = datetime.now(UTC)
            user = UserModel(
                id=uuid4(),
                email=f"worker-{uuid4()}@example.com",
                hashed_password="unused",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
            session.flush()
            source = SourceModel(
                id=uuid4(),
                owner_id=user.id,
                name="worker",
                slug=str(uuid4()),
                secret=None,
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            endpoint = EndpointModel(
                id=uuid4(),
                owner_id=user.id,
                name="receiver",
                url="https://receiver.worker/hook",
                secret="test-signing-only",
                is_active=True,
                failure_count=0,
                created_at=now,
                updated_at=now,
            )
            session.add_all([source, endpoint])
            session.flush()
            event = WebhookEventModel(
                id=uuid4(),
                source_id=source.id,
                payload={"ok": True},
                headers={
                    "Authorization": "legacy-auth",
                    "X-API-Key": "legacy-key",
                    "Cookie": "legacy-cookie",
                    "Host": "internal",
                    "Content-Length": "999",
                    "X-Webhook-Signature": "stale",
                    "X-Custom": "allowed",
                },
                idempotency_key=None,
                event_type="test",
                received_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(event)
            session.flush()
            attempt = DeliveryAttemptModel(
                id=uuid4(),
                event_id=event.id,
                endpoint_id=endpoint.id,
                attempt_number=1,
                status=DeliveryStatus.PENDING,
                attempted_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(attempt)
            session.commit()
            try:
                yield factory, attempt.id, event.id, endpoint.id
            finally:
                transaction.rollback()


def test_worker_success_signature_and_repeat_is_noop(worker_delivery):
    factory, attempt_id, event_id, endpoint_id = worker_delivery
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook").mock(
            return_value=Response(200, json={"ok": True})
        )
        result = task_module.deliver_webhook.apply(
            args=[str(attempt_id), str(event_id), str(endpoint_id)], throw=True
        )
        assert result.result["status"] == "success"
        assert request.call_count == 1
        assert (
            request.calls[0]
            .request.headers["X-Webhook-Signature"]
            .startswith("sha256=")
        )
        task_module.deliver_webhook.apply(
            args=[str(attempt_id), str(event_id), str(endpoint_id)], throw=True
        )
        assert request.call_count == 1
    with factory() as session:
        assert (
            session.get(DeliveryAttemptModel, attempt_id).status
            == DeliveryStatus.SUCCESS
        )


def test_redis_reset_failure_does_not_repeat_success(worker_delivery, monkeypatch):
    import redis

    def unavailable(*args, **kwargs):
        raise redis.ConnectionError("synthetic reset outage")

    monkeypatch.setattr(task_module.SyncCircuitBreaker, "reset", unavailable)
    factory, attempt_id, event_id, endpoint_id = worker_delivery
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook").mock(
            return_value=Response(200, json={"ok": True})
        )
        result = task_module.deliver_webhook.apply(
            args=[str(attempt_id), str(event_id), str(endpoint_id)], throw=True
        )
        assert result.result["status"] == "success"
        assert request.call_count == 1
    with factory() as session:
        assert (
            session.get(DeliveryAttemptModel, attempt_id).status
            == DeliveryStatus.SUCCESS
        )


def test_late_soft_timeout_preserves_success(worker_delivery, monkeypatch):
    from billiard.exceptions import SoftTimeLimitExceeded

    def timeout(*args, **kwargs):
        raise SoftTimeLimitExceeded()

    monkeypatch.setattr(task_module.SyncCircuitBreaker, "reset", timeout)
    factory, attempt_id, event_id, endpoint_id = worker_delivery
    args = [str(attempt_id), str(event_id), str(endpoint_id)]
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook").mock(
            return_value=Response(200)
        )
        with pytest.raises(SoftTimeLimitExceeded):
            task_module.deliver_webhook.apply(args=args, throw=True)
        with factory() as session:
            assert (
                session.get(DeliveryAttemptModel, attempt_id).status
                == DeliveryStatus.SUCCESS
            )
        result = task_module.deliver_webhook.apply(args=args, throw=True)
        assert result.result["status"] == "success"
        assert request.call_count == 1


@pytest.mark.parametrize("failure", [500, ConnectTimeout("controlled timeout")])
def test_worker_failures_exhaust_and_count_attempts(worker_delivery, failure):
    factory, attempt_id, event_id, endpoint_id = worker_delivery
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook")
        if isinstance(failure, int):
            request.mock(return_value=Response(failure))
        else:
            request.mock(side_effect=failure)
        result = task_module.deliver_webhook.apply(
            args=[str(attempt_id), str(event_id), str(endpoint_id)], throw=False
        )
        assert result.result["status"] == "failed"
        assert request.call_count == 5
    with factory() as session:
        assert (
            session.get(DeliveryAttemptModel, attempt_id).status
            == DeliveryStatus.EXHAUSTED
        )
        assert session.get(EndpointModel, endpoint_id).failure_count == 5


@pytest.mark.parametrize(
    "operation,response_code,initial_failures,expected_calls",
    [
        ("get", 200, 0, 1),
        ("incr", 500, 0, 5),
        ("expire", 500, 0, 5),
        ("get", 500, 9, 1),
        ("get", 500, 10, 0),
    ],
)
def test_redis_outage_preserves_durable_delivery_state(
    worker_delivery,
    monkeypatch,
    operation,
    response_code,
    initial_failures,
    expected_calls,
):
    factory, attempt_id, event_id, endpoint_id = worker_delivery
    with factory() as session:
        session.get(EndpointModel, endpoint_id).failure_count = initial_failures
        session.commit()

    def unavailable(*args, **kwargs):
        raise redis.TimeoutError("synthetic circuit breaker outage")

    monkeypatch.setattr(redis.Redis, operation, unavailable)
    if initial_failures >= 9:
        retry = Mock(side_effect=AssertionError("Durable threshold must stop retry"))
        monkeypatch.setattr(task_module.deliver_webhook, "retry", retry)
    with respx.mock as boundary:
        request = boundary.post("https://receiver.worker/hook").mock(
            return_value=Response(response_code)
        )
        result = task_module.deliver_webhook.apply(
            args=[str(attempt_id), str(event_id), str(endpoint_id)], throw=False
        )
        assert result.successful()
        assert request.call_count == expected_calls
    if initial_failures >= 9:
        retry.assert_not_called()
    with factory() as session:
        delivery = session.get(DeliveryAttemptModel, attempt_id)
        endpoint = session.get(EndpointModel, endpoint_id)
        assert delivery.status == (
            DeliveryStatus.SUCCESS if response_code == 200 else DeliveryStatus.EXHAUSTED
        )
        assert endpoint.failure_count == (
            0 if response_code == 200 else initial_failures + expected_calls
        )


def test_circuit_client_has_bounded_wait_and_is_closed(worker_delivery, monkeypatch):
    original = redis.Redis.from_url
    clients = []

    def create_client(*args, **kwargs):
        client = original(*args, **kwargs)
        client.close = Mock(wraps=client.close)
        clients.append(client)
        return client

    monkeypatch.setattr(redis.Redis, "from_url", create_client)
    result = task_module.deliver_webhook.apply(
        args=[str(uuid4()), str(uuid4()), str(uuid4())], throw=True
    )
    assert result.result["status"] == "failed"
    (client,) = clients
    options = client.connection_pool.connection_kwargs
    assert 0 < options["socket_connect_timeout"] <= 0.5
    assert 0 < options["socket_timeout"] <= 0.5
    assert options["retry"].get_retries() == 0
    client.close.assert_called_once()
