"""Checks every trading run makes before touching the account."""

from __future__ import annotations

from datetime import date

from ..alerts.messages import alert_text
from .deps import Deps


async def wrong_account(deps: Deps, session: date) -> bool:
    """True (after alerting) when a non-prod env is pointed at a live account."""
    if deps.env != "prod" and await deps.broker.is_live():
        await deps.notifier.send(alert_text(
            deps.env, session, f"the account is LIVE but env {deps.env} trades demo only; "
            "nothing done"))
        return True
    return False
