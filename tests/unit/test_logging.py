from __future__ import annotations

import structlog

from src.core.logging import configure_logging


def test_configure_logging_debug_and_prod_paths() -> None:
    configure_logging(debug=False)
    assert structlog.is_configured() is True

    configure_logging(debug=True)
    assert structlog.is_configured() is True

