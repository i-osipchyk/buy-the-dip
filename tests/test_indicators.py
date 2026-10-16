"""Indicators (ARCHITECTURE §2.1) against the spec's §4 reference values."""

from datetime import date

import pytest

from btd.core import indicators

from bars import reference_bars


def test_meta_on_its_signal_day_matches_the_spec():
    row = indicators(reference_bars("META")).loc[date(2026, 9, 25)]

    assert row.close == pytest.approx(751.66, abs=0.005)
    assert row.atr5 == pytest.approx(41.937, abs=0.0005)
    assert row.sma200 == pytest.approx(625.90, abs=0.005)
    assert row.volpct == pytest.approx(5.58, abs=0.005)
    assert row.ret == pytest.approx(751.66 / 777.59 - 1, abs=1e-5)


@pytest.mark.parametrize(("ticker", "day", "close", "atr5", "volpct", "ret_pct"), [
    ("EXPE", date(2026, 9, 8), 274.55, 14.182, 5.17, -7.88),
    ("GLW", date(2026, 10, 7), 163.25, 8.064, 4.94, -3.39),
    ("CF", date(2026, 9, 18), 127.70, 5.850, 4.58, -4.57),
])
def test_the_other_reference_signals_match_the_spec(ticker, day, close, atr5, volpct, ret_pct):
    row = indicators(reference_bars(ticker)).loc[day]

    assert row.close == pytest.approx(close, abs=0.005)
    assert row.atr5 == pytest.approx(atr5, abs=0.0005)
    assert row.volpct == pytest.approx(volpct, abs=0.005)
    assert 100 * row.ret == pytest.approx(ret_pct, abs=0.005)


def test_a_row_with_a_non_positive_price_is_dropped_before_computing():
    bars = reference_bars("META")
    before, broken, after = bars.index[-12:-9]
    bars.loc[broken, "low"] = 0.0                             # a broken print

    got = indicators(bars)

    assert len(got) == len(bars) - 1
    assert got.ret.iloc[-10] == pytest.approx(
        bars.close[after] / bars.close[before] - 1)           # compared with the row before it


def test_a_duplicated_session_keeps_its_last_row():
    import pandas as pd
    bars = reference_bars("META")
    revised = bars.iloc[[-1]].assign(close=740.00, ts=bars.ts.iloc[-1] + 3600)   # same NY date

    got = indicators(pd.concat([bars, revised], ignore_index=True))

    assert len(got) == len(bars)
    assert got.close.iloc[-1] == 740.00


def test_a_ticker_with_fewer_than_220_rows_is_excluded():
    bars = reference_bars("META")

    assert indicators(bars.tail(219)) is None
    assert indicators(bars.tail(220)) is not None
