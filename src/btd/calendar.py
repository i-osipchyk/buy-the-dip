"""NYSE sessions (exchange_calendars XNYS): which days trade, and holding-day counts."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import exchange_calendars as xc

NY = ZoneInfo("America/New_York")
SESSION_CLOSE = time(16, 0)


class Calendar:
    def __init__(self) -> None:
        self._xnys = xc.get_calendar("XNYS")

    def is_session(self, day: date) -> bool:
        return bool(self._xnys.is_session(day))

    def next_session(self, day: date) -> date:
        return date.fromisoformat(str(self._xnys.next_session(day).date()))

    def previous_session(self, day: date) -> date:
        return date.fromisoformat(str(self._xnys.previous_session(day).date()))

    def held(self, entry: date, day: date) -> int:
        """Sessions from the entry session to ``day``: 0 on the entry day itself."""
        return int(self._xnys.sessions_distance(entry, day)) - 1

    def close_at(self, day: date) -> datetime:
        """16:00 New York on ``day`` (entry orders expire then; early closes end earlier and
        the order simply can't fill after them)."""
        return datetime.combine(day, SESSION_CLOSE, NY)
