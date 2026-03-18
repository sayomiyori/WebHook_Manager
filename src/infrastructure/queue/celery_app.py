from __future__ import annotations

from celery import Celery  # type: ignore[import-untyped]

from src.core.config import settings

celery = Celery(
    "webhook_manager",
    broker=str(settings.CELERY_BROKER_URL),
    backend=str(settings.CELERY_BROKER_URL),
    include=[
        "src.infrastructure.queue.tasks.deliver_webhook",
    ],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

