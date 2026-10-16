"""The open-exit run (09:35 New York): sell what the previous evening flagged."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from btd.calendar import Calendar
from btd.runs.deps import Deps
from btd.runs.open_exit import open_exit
from btd.store import DirStore

from fake_broker import FakeBars, FakeBroker, FakeClock, FakeConstituents, FakeNotifier

NY = ZoneInfo("America/New_York")
MORNING = datetime(2026, 9, 28, 9, 35, tzinfo=NY)                 # Monday; Friday flagged


def _position(position_id, symbol_id, label, volume=700):
    from btd.broker import Position
    return Position(position_id=position_id, symbol_id=symbol_id, side="buy", volume=volume,
                    entry_price=100.0, stop_loss=None, label=label,
                    opened_at=datetime(2026, 9, 11, 9, 45, tzinfo=NY))


def _deps(tmp_path, broker, now=MORNING):
    deps = Deps(env="dev", broker=broker, store=DirStore(tmp_path), notifier=FakeNotifier(),
                clock=FakeClock(now), bars=FakeBars(), constituents=FakeConstituents(),
                calendar=Calendar())
    deps.store.put_json("dev/records/2026-09-25.json", {
        "session": "2026-09-25", "env": "dev", "complete": True, "positions": [
            {"position_id": 5400, "ticker": "META", "held": 10, "exit": "time"},
            {"position_id": 5401, "ticker": "GLW", "held": 3, "exit": "rebound"},
            {"position_id": 5402, "ticker": "EXPE", "held": 2, "exit": None}]})
    return deps


def test_sells_the_flagged_positions_at_market_and_nothing_else(tmp_path):
    broker = FakeBroker({})
    broker.positions = {5400: _position(5400, 334, "btd-dev"),
                        5401: _position(5401, 336, "btd-dev", volume=3200),
                        5402: _position(5402, 335, "btd-dev"),
                        9001: _position(9001, 1, "gtb")}
    deps = _deps(tmp_path, broker)

    asyncio.run(open_exit(deps))

    assert broker.closed == [5400, 5401]
    assert set(broker.positions) == {5402, 9001}


def test_records_each_exit_with_its_fill_and_tolerates_a_target_that_sold_at_the_open(tmp_path):
    broker = FakeBroker({})
    broker.positions = {5400: _position(5400, 334, "btd-dev")}      # 5401: the TP sold it already
    broker.fill_price = {5400: 702.10}
    deps = _deps(tmp_path, broker)
    broker.now = deps.clock

    asyncio.run(open_exit(deps))

    doc = deps.store.get_json("dev/open_exits/2026-09-28.json")
    assert doc["complete"] is True
    assert [(e["ticker"], e["reason"], e["result"], e["price"]) for e in doc["exits"]] == [
        ("META", "time", "closed", 702.10), ("GLW", "rebound", "already closed", None)]
    assert deps.notifier.sent == ["[dev] 2026-09-28 open exits\n"
                                  "META sold @ 702.10 (time)\nGLW already closed (rebound)"]


def test_a_second_run_that_morning_does_nothing(tmp_path):
    broker = FakeBroker({})
    broker.positions = {5400: _position(5400, 334, "btd-dev")}
    deps = _deps(tmp_path, broker)
    asyncio.run(open_exit(deps))
    broker.calls.clear()
    deps.notifier.sent.clear()

    asyncio.run(open_exit(deps))

    assert broker.closed == [5400]
    assert broker.calls == [] and deps.notifier.sent == []


def test_dev_refuses_a_live_account(tmp_path):
    broker = FakeBroker({}, live=True)
    broker.positions = {5400: _position(5400, 334, "btd-dev")}
    deps = _deps(tmp_path, broker)

    asyncio.run(open_exit(deps))

    assert broker.closed == []
    assert deps.notifier.sent == [
        "ALERT [dev] 2026-09-28: the account is LIVE but env dev trades demo only; nothing done"]
