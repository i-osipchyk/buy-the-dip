"""The heartbeat (23:15 New York): catches an evening run that never finished."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from btd.calendar import Calendar
from btd.runs.deps import Deps
from btd.runs.heartbeat import heartbeat
from btd.store import DirStore

from fake_broker import FakeBars, FakeBroker, FakeClock, FakeConstituents, FakeNotifier

NY = ZoneInfo("America/New_York")


def _deps(tmp_path, now):
    return Deps(env="dev", broker=FakeBroker({}), store=DirStore(tmp_path),
                notifier=FakeNotifier(), clock=FakeClock(now), bars=FakeBars(),
                constituents=FakeConstituents(), calendar=Calendar())


def test_alerts_when_the_sessions_record_is_not_complete(tmp_path):
    deps = _deps(tmp_path, datetime(2026, 9, 25, 23, 15, tzinfo=NY))

    asyncio.run(heartbeat(deps))

    assert deps.notifier.sent == [
        "ALERT [dev] 2026-09-25: no complete evening record by 23:15: the evening run did not "
        "finish"]


def test_quiet_when_the_record_is_complete_or_there_was_no_session(tmp_path):
    deps = _deps(tmp_path, datetime(2026, 9, 25, 23, 15, tzinfo=NY))
    deps.store.put_json("dev/records/2026-09-25.json", {"complete": True})
    asyncio.run(heartbeat(deps))
    deps.clock.set(datetime(2026, 9, 26, 23, 15, tzinfo=NY))            # Saturday
    asyncio.run(heartbeat(deps))

    assert deps.notifier.sent == []
