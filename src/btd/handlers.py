"""Lambda entry points. One image, one function per handler (infra/main.tf `functions`).

Keep handlers thin: load env, call into the package, flush telemetry, return.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from btd.config import load_env

logging.getLogger().setLevel(logging.INFO)
# httpx logs each request URL at INFO, and Telegram's carries the bot token (seen 2026-10-19).
logging.getLogger("httpx").setLevel(logging.WARNING)
load_env()  # once per cold start
logger = logging.getLogger(__name__)


def example(event: dict[str, Any], context: Any) -> dict[str, Any]:
    logger.info("example run in %s (%s)", os.getenv("ENV"), os.getenv("GIT_SHA"))
    return {"ok": True}


def spike_fetch(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Spike item 1 (throwaway): Wikipedia + yfinance from AWS. Read-only."""
    from btd import spike

    return spike.fetch()


# The trading runs (ARCHITECTURE §5); wiring in btd.runs.app.
from btd.runs.app import (  # noqa: E402
    evening_handler,
    heartbeat_handler,
    morning_check_handler,
    open_exit_handler,
)

__all__ = ["evening_handler", "heartbeat_handler", "morning_check_handler", "open_exit_handler",
           "example", "spike_fetch"]
