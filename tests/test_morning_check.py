"""The morning check (09:50 New York): the broker matches last evening's record."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from btd.broker import PendingOrder, Position
from btd.calendar import Calendar
from btd.runs.deps import Deps
from btd.runs.morning_check import morning_check
from btd.store import DirStore

from fake_broker import FakeBars, FakeBroker, FakeClock, FakeConstituents, FakeNotifier

NY = ZoneInfo("America/New_York")
CHECK = datetime(2026, 9, 28, 9, 50, tzinfo=NY)
EXPIRY = datetime(2026, 9, 28, 16, 0, tzinfo=NY)


def _position(position_id, take_profit, label="btd-dev"):
    return Position(position_id=position_id, symbol_id=335, side="buy", volume=1900,
                    entry_price=262.0, stop_loss=None, label=label,
                    opened_at=datetime(2026, 9, 23, 9, 50, tzinfo=NY), take_profit=take_profit)


def _order(order_id, client_order_id, expiry=EXPIRY):
    return PendingOrder(order_id=order_id, symbol_id=334, side="buy", volume=700, stop_price=0.0,
                        stop_loss=None, label="btd-dev", client_order_id=client_order_id,
                        expiry=expiry, limit_price=713.92)


def _deps(tmp_path, broker):
    deps = Deps(env="dev", broker=broker, store=DirStore(tmp_path), notifier=FakeNotifier(),
                clock=FakeClock(CHECK), bars=FakeBars(), constituents=FakeConstituents(),
                calendar=Calendar())
    deps.store.put_json("dev/records/2026-09-25.json", {
        "session": "2026-09-25", "env": "dev", "complete": True,
        "positions": [{"position_id": 5402, "ticker": "EXPE", "held": 2, "target": 271.36,
                       "exit": None},
                      {"position_id": 5400, "ticker": "GLW", "held": 10, "target": None,
                       "exit": "time"}],
        "orders": [{"client_order_id": "btd-dev-20260928-META-E", "ticker": "META",
                    "order_id": 1000, "status": "placed"}]})
    return deps


def test_quiet_when_the_broker_matches_last_evenings_record(tmp_path):
    broker = FakeBroker({})
    broker.positions = {5402: _position(5402, 271.36)}
    broker.orders = {1000: _order(1000, "btd-dev-20260928-META-E")}
    deps = _deps(tmp_path, broker)

    asyncio.run(morning_check(deps))

    assert deps.notifier.sent == []


def test_a_flagged_position_still_open_alerts(tmp_path):
    broker = FakeBroker({})
    broker.positions = {5402: _position(5402, 271.36), 5400: _position(5400, None)}
    broker.orders = {1000: _order(1000, "btd-dev-20260928-META-E")}
    deps = _deps(tmp_path, broker)

    asyncio.run(morning_check(deps))

    assert deps.notifier.sent == [
        "ALERT [dev] 2026-09-28: GLW (position 5400) should have been sold at the open (time) "
        "but is still open"]


def test_a_position_without_tonights_take_profit_alerts(tmp_path):
    broker = FakeBroker({})
    broker.positions = {5402: _position(5402, None)}
    broker.orders = {1000: _order(1000, "btd-dev-20260928-META-E")}
    deps = _deps(tmp_path, broker)

    asyncio.run(morning_check(deps))

    assert deps.notifier.sent == [
        "ALERT [dev] 2026-09-28: EXPE (position 5402) has take-profit None, expected 271.36"]


def test_an_entry_order_neither_pending_nor_filled_alerts_and_a_filled_one_is_fine(tmp_path):
    from btd.broker import Deal
    broker = FakeBroker({})
    broker.positions = {5402: _position(5402, 271.36)}
    deps = _deps(tmp_path, broker)

    asyncio.run(morning_check(deps))
    assert deps.notifier.sent == ["ALERT [dev] 2026-09-28: entry order btd-dev-20260928-META-E "
                                  "(1000) is neither pending nor filled"]

    deps.notifier.sent.clear()
    broker.deal_list = [Deal(7, 1000, 5600, "buy", 700, 713.92,
                             datetime(2026, 9, 28, 9, 30, 1, tzinfo=NY), -0.14, False, None, None)]
    asyncio.run(morning_check(deps))
    assert deps.notifier.sent == []


def test_an_entry_order_with_the_wrong_expiry_alerts(tmp_path):
    broker = FakeBroker({})
    broker.positions = {5402: _position(5402, 271.36)}
    broker.orders = {1000: _order(1000, "btd-dev-20260928-META-E",
                                  expiry=datetime(2026, 9, 29, 16, 0, tzinfo=NY))}
    deps = _deps(tmp_path, broker)

    asyncio.run(morning_check(deps))

    assert deps.notifier.sent == [
        "ALERT [dev] 2026-09-28: entry order btd-dev-20260928-META-E (1000) expires "
        "2026-09-29 16:00:00-04:00, expected 2026-09-28 16:00:00-04:00"]
