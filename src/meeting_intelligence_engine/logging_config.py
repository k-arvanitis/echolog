from __future__ import annotations

import logging

from meeting_intelligence_engine.config import settings

_configured = False


def configure_logging() -> None:
    """Configure root logging once, idempotently. Safe to call from any entrypoint."""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    _configured = True
