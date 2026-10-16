"""plan(): one evening's decisions (ARCHITECTURE §2.2-2.5). Days are small hand-built tables."""

import pandas as pd
import pytest

from btd.core import Entry, Holding, plan

EQUITY = 50_000.0


def day(*rows: dict) -> pd.DataFrame:
    """A day-t table, one row per ticker. Defaults: a member in an uptrend, a quiet day."""
    base = {"close": 100.0, "high": 101.0, "prev_high": 102.0, "atr5": 2.0, "sma200": 90.0,
            "ret": -0.01, "volpct": 2.0, "member": True}
    return pd.DataFrame([base | r for r in rows]).set_index("ticker")


META_SIGNAL = {"ticker": "META", "close": 751.66, "high": 780.0, "prev_high": 790.0,
               "atr5": 41.937, "sma200": 625.90, "ret": -0.0333, "volpct": 5.58}


def test_a_volatile_dip_in_an_uptrend_gets_a_limit_order_sized_at_ten_percent():
    p = plan(day(META_SIGNAL), [], EQUITY)

    # spec §4: limit 751.66 - 0.9 * 41.937 = 713.92; 10% of 50k / 713.92 = 7.0036 -> 7.0 shares
    # Prices are exact: rounding to the venue's tick happens when the order is sent.
    assert p.entries == [Entry(ticker="META", rank=1, limit=pytest.approx(713.9167), shares=7.0)]


def test_failing_any_one_signal_condition_means_no_order():
    signal = {"close": 100.0, "sma200": 90.0, "ret": -0.05, "volpct": 4.0, "member": True}
    p = plan(day(
        signal | {"ticker": "OK"},
        signal | {"ticker": "DOWNTREND", "sma200": 100.0},          # close must be > SMA200
        signal | {"ticker": "SMALLDROP", "ret": -0.03},             # must fall MORE than 3%
        signal | {"ticker": "CALM", "volpct": 3.0},                 # VolPct must exceed 3
        signal | {"ticker": "LEFT", "member": False},
    ), [], EQUITY)

    assert [e.ticker for e in p.entries] == ["OK"]


def _signals(n: int, **overrides) -> list[dict]:
    """n distinct signals with VolPct 4.0, 4.1, ... (ticker S00, S01, ...)."""
    return [{"ticker": f"S{i:02d}", "ret": -0.05, "volpct": 4.0 + i / 10} | overrides
            for i in range(n)]


def test_orders_only_the_ten_most_volatile_and_records_the_rest_as_no_slot():
    p = plan(day(*_signals(12)), [], EQUITY)

    assert [e.ticker for e in p.entries] == [f"S{i:02d}" for i in range(11, 1, -1)]
    assert [e.rank for e in p.entries] == list(range(1, 11))
    assert {c.ticker: c.status for c in p.candidates if c.status != "ordered"} == {
        "S01": "no_slot", "S00": "no_slot"}


def test_equal_volatility_is_ranked_by_ticker():
    p = plan(day({"ticker": "BBB", "ret": -0.05, "volpct": 5.0},
                 {"ticker": "AAA", "ret": -0.05, "volpct": 5.0}), [], EQUITY)

    assert [e.ticker for e in p.entries] == ["AAA", "BBB"]


META_ENTRY_DAY = {"ticker": "META", "close": 715.62, "high": 750.58, "prev_high": 780.0,
                  "atr5": 32.181, "sma200": 630.0, "ret": -0.048, "volpct": 4.5}


def test_an_open_position_gets_a_target_half_an_atr_above_the_close():
    meta = Holding("META", shares=7.0, entry_price=713.92, held=0)

    p = plan(day(META_ENTRY_DAY), [meta], EQUITY)

    assert p.targets == {"META": pytest.approx(731.7105)}    # spec §4: 715.62 + 0.5 * 32.181
    assert p.exits == {}
    assert p.entries == []                       # held: not a candidate even though it signals


def test_a_close_above_the_previous_high_sells_at_the_next_open():
    pos = Holding("XYZ", shares=50.0, entry_price=95.0, held=0)   # also on the entry day itself

    p = plan(day({"ticker": "XYZ", "close": 103.0, "prev_high": 102.0}), [pos], EQUITY)

    assert p.exits == {"XYZ": "rebound"}
    assert p.targets == {}


def test_ten_sessions_held_sells_at_the_next_open_but_nine_does_not():
    nine = Holding("NINE", shares=50.0, entry_price=95.0, held=9)
    ten = Holding("TEN", shares=50.0, entry_price=95.0, held=10)

    p = plan(day({"ticker": "NINE"}, {"ticker": "TEN"}), [nine, ten], EQUITY)

    assert p.exits == {"TEN": "time"}
    assert p.targets == {"NINE": 101.0}          # 100 + 0.5 * 2


def test_leaving_the_index_sells_at_the_next_open_unless_another_exit_applies_first():
    left = Holding("LEFT", shares=50.0, entry_price=95.0, held=3)
    left_and_rebounds = Holding("BOTH", shares=50.0, entry_price=95.0, held=3)

    p = plan(day({"ticker": "LEFT", "member": False},
                 {"ticker": "BOTH", "member": False, "close": 103.0, "prev_high": 102.0}),
             [left, left_and_rebounds], EQUITY)

    assert p.exits == {"LEFT": "removed", "BOTH": "rebound"}


def test_a_position_leaving_at_the_open_frees_its_slot_for_that_mornings_entries():
    holdings = [Holding(f"H{i}", shares=50.0, entry_price=95.0, held=10 if i == 9 else 1)
                for i in range(10)]

    p = plan(day(*[{"ticker": h.ticker} for h in holdings], *_signals(2)), holdings, EQUITY)

    assert p.exits == {"H9": "time"}
    assert [e.ticker for e in p.entries] == ["S01"]


def test_a_position_timed_out_tonight_can_be_bought_again_if_it_signals():
    old = Holding("XYZ", shares=50.0, entry_price=95.0, held=10)

    p = plan(day({"ticker": "XYZ", "ret": -0.05, "volpct": 4.0}), [old], EQUITY)

    assert p.exits == {"XYZ": "time"}
    assert [e.ticker for e in p.entries] == ["XYZ"]


def test_orders_never_take_gross_exposure_above_equity_and_the_lowest_rank_loses_out():
    holdings = [Holding(f"H{i}", shares=60.0, entry_price=95.0, held=1) for i in range(8)]
    # 8 x 60 shares x close 100 = 48,000 held; 2,000 of the 50,000 left

    p = plan(day(*[{"ticker": h.ticker} for h in holdings], *_signals(2)), holdings, EQUITY)

    assert [(e.ticker, e.shares) for e in p.entries] == [("S01", 20.3)]   # 2,000 / 98.2 (L)
    assert {c.ticker: c.status for c in p.candidates} == {"S01": "ordered", "S00": "cap_trim"}


def test_a_slot_too_small_for_the_minimum_volume_is_skipped():
    pricey = {"ticker": "PRICEY", "close": 60_000.0, "sma200": 50_000.0, "atr5": 2_000.0,
              "ret": -0.05, "volpct": 3.5}                    # L = 58,200: 5,000 buys 0.08 share

    p = plan(day(pricey), [], EQUITY)

    assert p.entries == []
    assert [(c.ticker, c.status) for c in p.candidates] == [("PRICEY", "min_size")]


def test_a_held_stock_with_no_bar_today_is_left_alone():
    halted = Holding("HALT", shares=50.0, entry_price=95.0, held=10)

    p = plan(day({"ticker": "OTHER"}), [halted], EQUITY)

    assert (p.exits, p.targets) == ({}, {})       # no new decision: its current TP stays


def test_a_held_stock_that_signals_is_recorded_as_held_without_taking_a_rank():
    meta = Holding("META", shares=7.0, entry_price=713.92, held=0)

    p = plan(day(META_ENTRY_DAY, *_signals(1)), [meta], EQUITY)

    assert [(c.ticker, c.rank, c.status) for c in p.candidates] == [
        ("S00", 1, "ordered"), ("META", 0, "held")]
