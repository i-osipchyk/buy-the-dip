"""simulate(): the backtest loop around core.plan(), against the spec's §4 reference trades."""

from datetime import date

import pytest

from btd.backtest import Config, Membership, simulate
from btd.core import indicators

from bars import reference_bars

REFERENCE = ["META", "EXPE", "GLW", "CF"]
ALWAYS_MEMBERS = Membership([date(2000, 1, 1)], [frozenset(REFERENCE)])


@pytest.fixture(scope="module")
def trades():
    panel = {t: indicators(reference_bars(t)) for t in REFERENCE}
    trades, _ = simulate(panel, ALWAYS_MEMBERS,
                         Config(start=date(2026, 9, 1), end=date(2026, 10, 14), cost_bp=3.0))
    return trades.set_index(["ticker", "entry_date"])


def test_meta_is_bought_at_the_limit_and_sold_at_the_next_days_target(trades):
    t = trades.loc[("META", date(2026, 9, 28))]

    assert (t.exit_date, t.why) == (date(2026, 9, 29), "target")
    assert t.entry == pytest.approx(713.92, abs=0.005)
    assert t.exit == pytest.approx(731.71, abs=0.005)


@pytest.mark.parametrize(("ticker", "entry_day", "entry", "exit_day", "exit"), [
    ("EXPE", date(2026, 9, 9), 261.79, date(2026, 9, 10), 279.57),
    ("GLW", date(2026, 10, 8), 155.99, date(2026, 10, 9), 157.11),     # target below the open
    ("CF", date(2026, 9, 21), 122.44, date(2026, 9, 28), 117.30),      # trails down, gap fill
])
def test_the_other_reference_trades_match_the_spec(trades, ticker, entry_day, entry, exit_day,
                                                   exit):
    t = trades.loc[(ticker, entry_day)]

    assert (t.exit_date, t.why) == (exit_day, "target")
    assert t.entry == pytest.approx(entry, abs=0.005)
    assert t.exit == pytest.approx(exit, abs=0.005)


# --- synthetic sessions: hand-built indicator rows -------------------------------------------

def _ticker(*sessions: dict):
    """An indicators()-shaped frame for consecutive sessions from 2026-03-02 (a Monday)."""
    import pandas as pd
    base = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "atr5": 2.0,
            "sma200": 90.0, "ret": 0.0, "volpct": 2.0}
    days = pd.bdate_range("2026-03-02", periods=len(sessions)).date
    return pd.DataFrame([base | s for s in sessions], index=pd.Index(days, name="date"))


SIGNAL = {"ret": -0.05, "volpct": 4.0}       # close 100, ATR 2 -> L = 98.20


def _run(panel):
    trades, equity = simulate(panel, Membership([date(2000, 1, 1)], [frozenset(panel)]),
                              Config(start=date(2026, 3, 2), end=date(2026, 3, 31), cost_bp=0.0))
    return trades, equity


def test_gaps_through_the_limit_and_the_target_fill_at_the_open():
    trades, _ = _run({"GAP": _ticker(
        SIGNAL,
        {"open": 97.0, "high": 99.0, "low": 96.0, "close": 98.0},     # opens below L = 98.20
        {"open": 100.5, "high": 101.0, "low": 100.0, "close": 100.8},  # opens above T = 99.00
        {})})

    (t,) = trades.itertuples()
    assert (t.entry, t.exit, t.why) == (97.0, 100.5, "target")


def test_a_rebound_sells_at_the_next_open():
    trades, _ = _run({"RB": _ticker(
        SIGNAL,
        {"open": 99.0, "high": 99.5, "low": 98.0, "close": 99.2},     # bought at 98.20; T 100.20
        {"open": 99.5, "high": 100.1, "low": 99.4, "close": 100.0},   # high < T; close 100.0 > 99.5
        {"open": 100.3, "high": 100.4, "low": 100.0, "close": 100.2},
        {})})

    (t,) = trades.itertuples()
    assert (t.entry, t.exit, t.why) == (98.2, 100.3, "close_gt_high")
    assert t.exit_date == date(2026, 3, 5)


def test_ten_sessions_without_a_target_or_rebound_sell_at_the_next_open():
    stuck = {"open": 97.0, "high": 97.5, "low": 96.5, "close": 97.0}   # no target, no rebound
    trades, _ = _run({"SLOW": _ticker(SIGNAL, *[stuck] * 11, {"open": 96.0}, {})})

    (t,) = trades.itertuples()
    # entered 03-03 (held 0); held = 10 at the close of 03-17; sold at the 03-18 open
    assert (t.entry_date, t.exit_date, t.why) == (date(2026, 3, 3), date(2026, 3, 18), "time")
    assert t.exit == 96.0


def test_positions_still_open_at_the_end_of_the_window_close_at_the_last_close():
    trades, _ = _run({"END": _ticker(SIGNAL, {"open": 99.0, "high": 99.5, "low": 98.0,
                                              "close": 98.5})})

    (t,) = trades.itertuples()
    assert (t.exit, t.why) == (98.5, "end")


def test_a_trades_return_pays_the_cost_on_both_sides_as_hermes_counts_it(trades):
    # (1 - 0.0003)^2 * 731.7105 / 713.9167 - 1, worked by hand from the spec's §4 inputs
    assert trades.loc[("META", date(2026, 9, 28))].ret == pytest.approx(0.024309, abs=1e-6)


def test_equity_moves_by_the_shares_bought_at_the_limit_size():
    _, equity = _run({"GAP": _ticker(
        SIGNAL,
        {"open": 97.0, "high": 99.0, "low": 96.0, "close": 98.0},
        {"open": 100.5, "high": 101.0, "low": 100.0, "close": 100.8},
        {})})

    # 10% of 100,000 at L = 98.20 -> 101.8 shares, filled at 97.00, sold at 100.50
    assert equity.iloc[-1] == pytest.approx(100_000 + 101.8 * (100.5 - 97.0))
