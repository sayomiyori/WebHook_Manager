"""Independent recovery of durable Telegram send intents."""

import logging
import time

from src.core.config import settings
from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.repositories.telegram_answer_repository import (
    TelegramSendRepository,
)
from src.infrastructure.queue.celery_app import celery_app

logger = logging.getLogger(__name__)


def enqueue(identity: str) -> None:
    with celery_app.connection_for_write(connect_timeout=2) as connection:
        connection.transport_options.update(
            socket_connect_timeout=2, socket_timeout=2, retry_on_timeout=False
        )
        connection.ensure_connection(max_retries=0)
        celery_app.send_task(
            "send_telegram_answer",
            args=[identity],
            queue="telegram_send",
            connection=connection,
            retry=False,
        )


def recover_answers_once(batch_size: int = 100) -> int:
    if not settings.TELEGRAM_REPLIES_ENABLED:
        return 0
    with sync_session_maker() as db:
        ids = TelegramSendRepository(db).recover_due(batch_size)
        db.commit()
    submitted = 0
    for identity in ids:
        try:
            enqueue(str(identity))
            submitted += 1
        except Exception:
            logger.warning("Telegram send notification unavailable")
            break
    return submitted


def main() -> None:
    while True:
        try:
            recover_answers_once()
        except Exception:
            logger.warning("Telegram send recovery unavailable")
        time.sleep(5)


if __name__ == "__main__":
    main()
