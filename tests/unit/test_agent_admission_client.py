import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from src.api.v1.schemas.telegram_ingress import (
    TelegramIngressEnvelope,
    TelegramMessagePayload,
)
from src.core.security import verify_hmac_signature
from src.infrastructure.platform.agent_admission import (
    AdmissionError,
    AgentAdmissionClient,
)
from tests.unit.test_telegram_configuration import configuration


def envelope():
    bot = uuid4()
    return TelegramIngressEnvelope(
        event_id=uuid4(),
        tenant_id=uuid4(),
        bot_id=bot,
        correlation_id=uuid4(),
        occurred_at=datetime.now(UTC),
        idempotency_key=f"telegram:{bot}:1",
        payload=TelegramMessagePayload(
            update_id=1, message_id=1, chat_id=7, question="Hello"
        ),
    )


async def test_admission_signs_immutable_bytes_and_validates_receipt():
    event, job, config = envelope(), uuid4(), configuration()

    def reply(request):
        assert verify_hmac_signature(
            request.content,
            config.WEBHOOK_AGENT_INGRESS_KEY.get_secret_value(),
            request.headers["X-Webhook-Signature"],
        )
        assert json.loads(request.content)["event_id"] == str(event.event_id)
        assert "authorization" not in request.headers
        return httpx.Response(
            202,
            json={
                "event_id": str(event.event_id),
                "job_id": str(job),
                "state": "pending",
            },
        )

    receipt = await AgentAdmissionClient(
        config, transport=httpx.MockTransport(reply)
    ).admit(event)
    assert receipt.job_id == job


@pytest.mark.parametrize(
    "status,terminal",
    [
        (401, True),
        (403, True),
        (404, True),
        (409, True),
        (422, True),
        (429, False),
        (500, False),
        (302, False),
    ],
)
async def test_admission_errors_are_classified_without_remote_content(status, terminal):
    config, event = configuration(), envelope()

    async def reply(request):
        return httpx.Response(
            status, json={"detail": "private remote description", "retry_after": 30}
        )

    with pytest.raises(AdmissionError) as caught:
        await AgentAdmissionClient(config, transport=httpx.MockTransport(reply)).admit(
            event
        )
    assert caught.value.terminal == terminal
    assert "private" not in str(caught.value)
    assert caught.value.retry_after == (30 if status == 429 else None)


async def test_mismatched_receipt_never_finalizes():
    async def reply(request):
        return httpx.Response(
            200,
            json={"event_id": str(uuid4()), "job_id": str(uuid4()), "state": "pending"},
        )

    with pytest.raises(AdmissionError) as caught:
        await AgentAdmissionClient(
            configuration(), transport=httpx.MockTransport(reply)
        ).admit(envelope())
    assert not caught.value.terminal


@pytest.mark.parametrize(
    "case", ["oversized", "compressed", "malformed", "extra", "wrong_type", "timeout"]
)
async def test_untrusted_receipts_fail_closed_and_do_not_retry(case):
    event = envelope()
    calls = []

    def reply(request):
        calls.append(request)
        if case == "timeout":
            raise httpx.ReadTimeout("private provider error", request=request)
        if case == "oversized":
            return httpx.Response(200, content=b" " * 65537)
        if case == "compressed":
            return httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, content=b"private"
            )
        if case == "malformed":
            return httpx.Response(200, content=b"private invalid JSON")
        body = {
            "event_id": str(event.event_id),
            "job_id": str(uuid4()),
            "state": "pending",
        }
        body.update({"private": "provider"} if case == "extra" else {"job_id": True})
        return httpx.Response(200, json=body)

    with pytest.raises(AdmissionError) as error:
        await AgentAdmissionClient(
            configuration(), transport=httpx.MockTransport(reply)
        ).admit(event)
    assert not error.value.terminal and len(calls) == 1
    assert "private" not in str(error.value)


@pytest.mark.parametrize(
    "retry,expected", [(True, None), (0, None), (3601, None), (15, 15)]
)
async def test_retry_after_body_is_a_bounded_integer(retry, expected):
    transport = httpx.MockTransport(
        lambda _: httpx.Response(429, json={"retry_after": retry})
    )
    with pytest.raises(AdmissionError) as error:
        await AgentAdmissionClient(configuration(), transport=transport).admit(
            envelope()
        )
    assert error.value.retry_after == expected
