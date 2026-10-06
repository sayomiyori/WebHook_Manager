"""Recover due platform publication intents independently of the broker."""

from __future__ import annotations

import argparse
import time

import structlog

from src.core.config import settings
from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.repositories.platform_outbox_repository import (
    PlatformOutboxRepository,
)
from src.infrastructure.queue.celery_app import celery_app
from src.infrastructure.queue.tasks.publish_platform_ingress import (
    publish_platform_ingress,
)

log = structlog.get_logger()


def enqueue(outbox_id: str) -> None:
    with celery_app.connection_for_write(connect_timeout=2) as connection:
        connection.transport_options.update(
            socket_connect_timeout=2, socket_timeout=2, retry_on_timeout=False
        )
        connection.ensure_connection(max_retries=0)
        publish_platform_ingress.apply_async(
            args=[outbox_id], connection=connection, retry=False
        )


def scan_once() -> int:
    settings.require_publication()
    with sync_session_maker() as session:
        ids = PlatformOutboxRepository(session).due_ids(100)
    submitted = 0
    for identifier in ids:
        try:
            enqueue(str(identifier))
            submitted += 1
        except Exception:  # noqa: BLE001
            # Never retain transport exceptions containing URLs or credentials.
            log.warning("platform_broker_unavailable")
            break
    return submitted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings.require_publication()
    while True:
        try:
            submitted = scan_once()
            log.info("platform_recovery_scan", submitted=submitted)
        except Exception:  # noqa: BLE001
            log.warning("platform_recovery_unavailable")
        if args.once:
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
