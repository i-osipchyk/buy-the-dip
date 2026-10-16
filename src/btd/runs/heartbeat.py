"""The heartbeat (ARCHITECTURE §5, 23:15 New York): alert if the session's evening record isn't
complete, which catches an evening run that never ran or never finished."""

from __future__ import annotations

from ..alerts.messages import alert_text
from .deps import Deps
from .evening import key


async def heartbeat(deps: Deps) -> None:
    now = deps.clock.now()
    session = now.date()
    if not deps.calendar.is_session(session):
        return
    if not (deps.store.get_json(key(deps.env, "records", session)) or {}).get("complete"):
        await deps.notifier.send(alert_text(
            deps.env, session, f"no complete evening record by {now:%H:%M}: the evening run did "
            "not finish"))
