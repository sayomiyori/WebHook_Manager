"""Recover due legacy deliveries independently of the Celery broker."""

import argparse
import time

import structlog

from src.infrastructure.db.base import sync_session_maker
from src.infrastructure.db.repositories.delivery_attempt_repository import (
    claim_due_deliveries,
)
from src.infrastructure.queue.delivery_publication import enqueue_delivery

log = structlog.get_logger()


def scan_once(batch_size: int = 100) -> int:
    with sync_session_maker() as session:
        deliveries = claim_due_deliveries(session, batch_size)
        session.commit()
    submitted = 0
    for delivery_id, event_id, endpoint_id in deliveries:
        try:
            enqueue_delivery(str(delivery_id), str(event_id), str(endpoint_id))
            submitted += 1
        except Exception:
            log.warning("delivery_broker_unavailable", delivery_id=str(delivery_id))
            break
    return submitted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            log.info("delivery_recovery_scan", submitted=scan_once())
        except Exception:
            log.warning("delivery_recovery_unavailable")
        if args.once:
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
