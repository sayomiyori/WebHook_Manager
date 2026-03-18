from __future__ import annotations

import logging

import structlog

from src.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(level=getattr(logging, settings.LOG_LEVEL))

    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL)
        ),
        cache_logger_on_first_use=True,
    )

