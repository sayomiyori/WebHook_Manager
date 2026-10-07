"""Explicit controlled-worker bootstrap; normal startup never imports it."""

import asyncio
import os
import time

import httpx
from billiard.exceptions import SoftTimeLimitExceeded  # type: ignore[import-untyped]

if os.getenv("TELEGRAM_SEND_VERIFICATION") != "controlled":
    raise RuntimeError("Controlled worker requires explicit verification configuration")

from src.infrastructure.queue.celery_app import celery_app as celery_app  # noqa: E402

original_client = httpx.AsyncClient


async def boundary(request: httpx.Request) -> httpx.Response:
    if request.url.host != "api.telegram.org":
        async with original_client(
            timeout=10, trust_env=False, follow_redirects=False
        ) as client:
            return await client.send(request)
    if (
        str(request.url)
        != "https://api.telegram.org/bot123456:synthetic_VERIFICATION-send-token/sendMessage"
    ):
        raise ValueError("Controlled worker refuses non-synthetic Telegram credentials")
    async with original_client(
        timeout=20, trust_env=False, follow_redirects=False
    ) as client:
        response = await client.post(
            os.environ["CONTROLLED_PROVIDER_URL"] + "/send",
            content=request.content,
            headers={"Content-Type": "application/json"},
        )
    if os.getenv("VERIFICATION_MODE") == "hard_timeout":
        # Ignore the async/soft deadlines only in this fault-injection transport.
        try:
            time.sleep(40)
        except SoftTimeLimitExceeded:
            time.sleep(20)
        await asyncio.sleep(0)
    return response


class ControlledClient(original_client):
    def __init__(self, **kwargs):
        kwargs["transport"] = httpx.MockTransport(boundary)
        super().__init__(**kwargs)


httpx.AsyncClient = ControlledClient
