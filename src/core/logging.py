from __future__ import annotations

import json
import logging
from typing import Any

import structlog


def suppress_platform_http_logging() -> None:
    # Telegram embeds credentials in URLs; HTTP debug records also carry headers.
    for name in (
        "httpx",
        "httpcore",
        "httpcore.connection",
        "httpcore.http11",
        "httpcore.http2",
        "httpcore.proxy",
        "httpcore.socks",
    ):
        logging.getLogger(name).disabled = True


def platform_sentry_event(event: Any, hint: Any) -> Any:
    if "api.telegram.org" in json.dumps(event, default=str):
        return None
    request = event.get("request")
    if isinstance(request, dict):
        # Platform registration will carry the bot token in the request body.
        request.pop("data", None)
        request.pop("headers", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
    return event


def platform_sentry_breadcrumb(crumb: Any, hint: Any) -> Any:
    if crumb.get("type") == "http" or "api.telegram.org" in json.dumps(
        crumb, default=str
    ):
        return None
    return crumb


def configure_logging(debug: bool = False) -> None:
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_logger_name,
    ]
    renderer: Any
    if debug:
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)
    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if debug else logging.INFO
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
