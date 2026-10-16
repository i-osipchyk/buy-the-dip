"""The evening run (ARCHITECTURE §5): fetch, plan, execute, record, summarise. Offline: fake
broker, store in a temp dir, recorded reference bars, the real XNYS calendar."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from btd.calendar import Calendar
from btd.runs.deps import Deps
from btd.runs.evening import evening
from btd.store import DirStore

from fake_broker import FakeBars, FakeBroker, FakeClock, FakeConstituents, FakeNotifier

NY = ZoneInfo("America/New_York")
NAMES = {"META.US": 334, "EXPE.US": 335, "GLW.US": 336, "CF.US": 337, "EURUSD": 1}


def _deps(tmp_path, now, broker=None, bars=None):
    return Deps(env="dev", broker=broker or FakeBroker(NAMES), store=DirStore(tmp_path),
                notifier=FakeNotifier(), clock=FakeClock(now), bars=bars or FakeBars(),
                constituents=FakeConstituents(), calendar=Calendar())


def test_does_nothing_on_a_day_without_a_session(tmp_path):
    deps = _deps(tmp_path, datetime(2026, 9, 26, 16, 30, tzinfo=NY))      # a Saturday

    asyncio.run(evening(deps))

    assert deps.broker.calls == []
    assert deps.notifier.sent == []
    assert not any(tmp_path.iterdir())


SIGNAL_EVENING = datetime(2026, 9, 25, 16, 30, tzinfo=NY)        # META's signal day (spec §4)


def test_places_tonights_entries_as_good_till_close_limits_with_our_ids(tmp_path):
    deps = _deps(tmp_path, SIGNAL_EVENING)

    asyncio.run(evening(deps))

    expiry = datetime(2026, 9, 28, 16, 0, tzinfo=NY)              # Monday: the next session
    assert deps.broker.placed == [
        {"symbol_id": 334, "side": "buy", "volume": 700, "limit": 713.92, "expiry": expiry,
         "label": "btd-dev", "client_order_id": "btd-dev-20260928-META-E"},
        {"symbol_id": 337, "side": "buy", "volume": 4500, "limit": 110.87, "expiry": expiry,
         "label": "btd-dev", "client_order_id": "btd-dev-20260928-CF-E"},
    ]   # 10% of the 50,000 genesis: 7.0 META at 713.92, 45.0 CF at 110.87


def test_records_the_session_and_a_second_run_that_evening_does_nothing(tmp_path):
    deps = _deps(tmp_path, SIGNAL_EVENING)
    asyncio.run(evening(deps))
    deps.broker.calls.clear()

    asyncio.run(evening(deps))

    record = deps.store.get_json("dev/records/2026-09-25.json")
    assert record["complete"] is True
    assert record["ledger"]["equity"] == 50_000.0
    assert [(c["ticker"], c["status"]) for c in record["candidates"]] == [
        ("META", "ordered"), ("CF", "ordered")]
    assert [(o["client_order_id"], o["limit"], o["volume"]) for o in record["orders"]] == [
        ("btd-dev-20260928-META-E", 713.92, 700), ("btd-dev-20260928-CF-E", 110.87, 4500)]
    assert len(deps.broker.placed) == 2
    assert deps.broker.calls == []


def test_a_retry_after_a_crash_finds_the_orders_already_placed(tmp_path):
    deps = _deps(tmp_path, SIGNAL_EVENING)
    asyncio.run(evening(deps))
    (tmp_path / "dev/records/2026-09-25.json").unlink()        # crashed before the record

    asyncio.run(evening(deps))

    assert len(deps.broker.placed) == 2
    record = deps.store.get_json("dev/records/2026-09-25.json")
    assert sorted(o["order_id"] for o in record["orders"]) == sorted(deps.broker.orders)


def _pending(order_id, label, client_order_id):
    from btd.broker import PendingOrder
    return PendingOrder(order_id=order_id, symbol_id=336, side="buy", volume=1000,
                        stop_price=0.0, stop_loss=None, label=label,
                        client_order_id=client_order_id, expiry=None, limit_price=150.0)


def test_stale_entry_orders_are_cancelled_and_other_labels_are_never_touched(tmp_path):
    broker = FakeBroker(NAMES)
    broker.orders = {1: _pending(1, "btd-dev", "btd-dev-20260925-GLW-E"),   # today's: expired
                     2: _pending(2, "gtb", "gtb-20260925-L"),               # not ours
                     3: _pending(3, "", "manual")}
    deps = _deps(tmp_path, SIGNAL_EVENING, broker=broker)

    asyncio.run(evening(deps))

    assert broker.cancelled == [1]
    assert {2, 3} <= set(broker.orders)


def _position(position_id, symbol_id, label, entry, opened, volume=700, take_profit=None):
    from btd.broker import Position
    return Position(position_id=position_id, symbol_id=symbol_id, side="buy", volume=volume,
                    entry_price=entry, stop_loss=None, label=label, opened_at=opened,
                    take_profit=take_profit)


ENTRY_EVENING = datetime(2026, 9, 28, 16, 30, tzinfo=NY)           # META bought at 713.92 today


def test_an_open_position_gets_tonights_target_and_other_positions_are_left_alone(tmp_path):
    broker = FakeBroker(NAMES)
    broker.positions = {
        5501: _position(5501, 334, "btd-dev", 713.92, datetime(2026, 9, 28, 10, 31, tzinfo=NY)),
        9001: _position(9001, 1, "gtb", 1.17, datetime(2026, 9, 28, 3, 0, tzinfo=NY))}
    deps = _deps(tmp_path, ENTRY_EVENING, broker=broker)

    asyncio.run(evening(deps))

    assert broker.amended == [(5501, 731.71)]                      # spec §4: 715.62 + 0.5 * 32.181
    (pos,) = deps.store.get_json("dev/records/2026-09-28.json")["positions"]
    assert (pos["position_id"], pos["ticker"], pos["held"], pos["target"], pos["exit"]) == (
        5501, "META", 0, 731.71, None)


def test_a_target_filled_today_is_recorded_and_its_profit_reaches_equity(tmp_path):
    from btd.broker import Deal
    broker = FakeBroker(NAMES)
    bought = datetime(2026, 9, 28, 10, 31, tzinfo=NY)
    sold = datetime(2026, 9, 29, 10, 2, tzinfo=NY)
    broker.deal_list = [
        Deal(1, 101, 5501, "buy", 700, 713.92, bought, -0.14, False, None, None),
        Deal(2, 102, 5501, "sell", 700, 731.71, sold, -0.14, True, 713.92, 124.53, swap=-0.87),
        Deal(3, 103, 9001, "sell", 100, 1.18, sold, -3.0, True, 1.17, 500.0, swap=0.0)]  # gtb
    deps = _deps(tmp_path, datetime(2026, 9, 29, 16, 30, tzinfo=NY), broker=broker)
    deps.store.put_json("dev/ledger/genesis.json",
                        {"start_capital": 50_000.0, "at": "2026-09-25T16:30:00-04:00"})
    deps.store.put_json("dev/ledger/state.json", {"btd_positions": [5501]})

    asyncio.run(evening(deps))

    record = deps.store.get_json("dev/records/2026-09-29.json")
    assert record["ledger"]["equity"] == pytest.approx(50_123.38)     # 124.53 - 0.87 - 0.28
    assert [(f["position_id"], f["price"], f["closing"]) for f in record["fills"]] == [
        (5501, 731.71, True)]


def test_a_position_timed_out_tonight_keeps_its_take_profit_and_may_be_bought_again(tmp_path):
    broker = FakeBroker(NAMES)
    broker.positions = {5400: _position(5400, 334, "btd-dev", 700.0,
                                        datetime(2026, 9, 11, 9, 45, tzinfo=NY),
                                        take_profit=760.0)}
    deps = _deps(tmp_path, SIGNAL_EVENING, broker=broker)          # 10 sessions after 09-11

    asyncio.run(evening(deps))

    assert broker.amended == []
    (pos,) = deps.store.get_json("dev/records/2026-09-25.json")["positions"]
    assert (pos["held"], pos["exit"], pos["target"]) == (10, "time", None)
    assert "btd-dev-20260928-META-E" in [p["client_order_id"] for p in broker.placed]


def test_missing_bars_before_the_deadline_wait_quietly_for_the_next_attempt(tmp_path):
    bars = FakeBars()
    bars.fail = True
    deps = _deps(tmp_path, datetime(2026, 9, 25, 17, 0, tzinfo=NY), bars=bars)

    asyncio.run(evening(deps))

    assert deps.broker.placed == [] and deps.broker.cancelled == []
    assert deps.store.get_json("dev/records/2026-09-25.json") is None
    assert deps.notifier.sent == []


def test_no_valid_bars_by_the_deadline_runs_degraded(tmp_path):
    bars = FakeBars()
    bars.fail = True
    broker = FakeBroker(NAMES)
    broker.positions = {
        5400: _position(5400, 334, "btd-dev", 700.0, datetime(2026, 9, 11, 9, 45, tzinfo=NY),
                        take_profit=760.0),                                   # held 10
        5402: _position(5402, 335, "btd-dev", 262.0, datetime(2026, 9, 23, 9, 50, tzinfo=NY),
                        take_profit=270.0)}                                   # held 2
    broker.orders = {1: _pending(1, "btd-dev", "btd-dev-20260925-GLW-E")}
    deps = _deps(tmp_path, datetime(2026, 9, 25, 23, 0, tzinfo=NY), broker=broker, bars=bars)

    asyncio.run(evening(deps))

    assert broker.placed == [] and broker.amended == []
    assert broker.cancelled == [1]
    record = deps.store.get_json("dev/records/2026-09-25.json")
    assert (record["complete"], record["degraded"]) == (True, True)
    assert {p["ticker"]: p["exit"] for p in record["positions"]} == {"META": "time", "EXPE": None}
    assert deps.notifier.sent == [
        "ALERT [dev] 2026-09-25: no valid bars by 23:00 (bars: 0 of 4 names have a complete "
        "2026-09-25 bar (need 98%); bars: held EXPE has no complete 2026-09-25 bar; bars: held "
        "META has no complete 2026-09-25 bar). Degraded: no entries, take-profits unchanged, "
        "time exits only"]


def test_a_broken_scrape_alerts_and_the_run_carries_on_with_the_previous_universe(tmp_path):
    deps = _deps(tmp_path, SIGNAL_EVENING)
    good = FakeConstituents().fetch()
    deps.store.put_json("dev/universe/latest.json", {
        "constituents": good, "venue": {"META": "META.US", "EXPE": "EXPE.US", "GLW": "GLW.US",
                                        "CF": "CF.US"}})
    deps.constituents.tickers = good[:300]

    asyncio.run(evening(deps))

    assert ("ALERT [dev] 2026-09-25: universe: 300 constituents scraped (expected 495-510); "
            "keeping the previous snapshot") in deps.notifier.sent
    assert len(deps.broker.placed) == 2


def _underwater(tmp_path, shares, now, entry=850.0):
    broker = FakeBroker(NAMES)
    broker.positions = {5300: _position(5300, 334, "btd-dev", entry,
                                        datetime(2026, 9, 22, 9, 40, tzinfo=NY),
                                        volume=shares * 100)}
    deps = _deps(tmp_path, now, broker=broker)
    deps.store.put_json("dev/ledger/genesis.json",
                        {"start_capital": 50_000.0, "at": "2026-09-21T16:30:00-04:00"})
    return deps


def _drawdown_alerts(deps):
    return [m for m in deps.notifier.sent if m.startswith("ALERT") and "drawdown" in m]


def test_crossing_minus_ten_percent_warns_once(tmp_path):
    # 50 x (751.66 - 860) = -5,417.00 (-10.8%); on 09-28 50 x (715.62 - 860) (-14.4%)
    deps = _underwater(tmp_path, 50, SIGNAL_EVENING, entry=860.0)

    asyncio.run(evening(deps))
    deps.clock.set(ENTRY_EVENING)
    asyncio.run(evening(deps))

    assert _drawdown_alerts(deps) == [
        "ALERT [dev] 2026-09-25: drawdown -10.8% (equity 44,583 vs peak 50,000): "
        "past the -10% warning"]
    assert deps.store.get_json("dev/records/2026-09-25.json")["ledger"]["drawdown"] == \
        pytest.approx(-0.1083, abs=1e-4)


def test_beyond_minus_fifteen_percent_alerts_every_evening(tmp_path):
    deps = _underwater(tmp_path, 100, SIGNAL_EVENING)     # -9,834.00 -> -19.7%

    asyncio.run(evening(deps))
    deps.clock.set(ENTRY_EVENING)
    asyncio.run(evening(deps))

    assert [m.split(":")[0] for m in _drawdown_alerts(deps)] == [
        "ALERT [dev] 2026-09-25", "ALERT [dev] 2026-09-28"]
    assert all("beyond the -15% review line" in m for m in _drawdown_alerts(deps))


def test_dev_refuses_a_live_account_and_touches_nothing(tmp_path):
    deps = _deps(tmp_path, SIGNAL_EVENING, broker=FakeBroker(NAMES, live=True))

    asyncio.run(evening(deps))

    assert deps.broker.placed == [] and deps.broker.calls == ["is_live"]
    assert deps.notifier.sent == [
        "ALERT [dev] 2026-09-25: the account is LIVE but env dev trades demo only; nothing done"]


def test_a_rejected_order_is_recorded_and_alerted_and_the_rest_still_go_out(tmp_path):
    broker = FakeBroker(NAMES)
    broker.reject["btd-dev-20260928-META-E"] = "NOT_ENOUGH_MONEY"
    deps = _deps(tmp_path, SIGNAL_EVENING, broker=broker)

    asyncio.run(evening(deps))

    assert [p["client_order_id"] for p in broker.placed] == ["btd-dev-20260928-CF-E"]
    orders = deps.store.get_json("dev/records/2026-09-25.json")["orders"]
    assert [(o["ticker"], o["order_id"], o["status"]) for o in orders] == [
        ("META", None, "rejected: NOT_ENOUGH_MONEY"), ("CF", 1000, "placed")]
    assert ("ALERT [dev] 2026-09-25: order btd-dev-20260928-META-E rejected: NOT_ENOUGH_MONEY"
            in deps.notifier.sent)


def test_the_evening_ends_with_a_summary(tmp_path):
    broker = FakeBroker(NAMES)
    broker.positions = {5402: _position(5402, 335, "btd-dev", 262.0,
                                        datetime(2026, 9, 23, 9, 50, tzinfo=NY), volume=1900)}
    deps = _deps(tmp_path, SIGNAL_EVENING, broker=broker)

    asyncio.run(evening(deps))

    # equity 50,000 + 19 x (264.17 - 262.00) = 50,041; EXPE T = 264.17 + 0.5 x 14.388 = 271.36;
    # CF: 5,004.12 / 110.871 = 45.13 -> 45.1 shares
    assert deps.notifier.sent[-1] == "\n".join([
        "[dev] 2026-09-25 evening",
        "equity 50,041 (drawdown 0.0%), 1/10 slots",
        "fills: none",
        "EXPE held 2: target 271.36",
        "tonight: META 7.0 @ 713.92, CF 45.1 @ 110.87",
    ])
