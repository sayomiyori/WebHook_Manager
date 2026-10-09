"""Bounded best-effort notifications for durable legacy delivery intents."""

from src.infrastructure.queue.celery_app import celery_app


def enqueue_delivery(
    delivery_id: str, event_id: str, endpoint_id: str, *, countdown: int = 0
) -> str | None:
    with celery_app.connection_for_write(connect_timeout=2) as connection:
        connection.transport_options.update(
            socket_connect_timeout=2, socket_timeout=2, retry_on_timeout=False
        )
        connection.ensure_connection(max_retries=0)
        result = celery_app.send_task(
            "deliver_webhook",
            args=[delivery_id, event_id, endpoint_id],
            countdown=countdown,
            connection=connection,
            retry=False,
        )
        return result.id if isinstance(result.id, str) else None
