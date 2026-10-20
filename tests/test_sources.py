"""Turning a yfinance download into the snapshot. Offline: a hand-built download frame."""

from datetime import date

import numpy as np
import pandas as pd

from btd.data.sources import snapshot_from_download


def _download(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """The shape of yf.download(..., group_by="ticker"): (ticker, price) columns, aligned."""
    return pd.concat(frames.values(), axis=1, keys=frames.keys(), names=["Ticker", "Price"])


def _bars(days: list[str], base: float) -> pd.DataFrame:
    n = len(days)
    return pd.DataFrame({"Open": base + np.arange(n), "High": base + 1 + np.arange(n),
                         "Low": base - 1 + np.arange(n), "Close": base + 0.5 + np.arange(n),
                         "Volume": 1000.0}, index=pd.DatetimeIndex(days, name="Date"))


def test_a_ticker_whose_download_failed_is_left_out_and_the_rest_are_kept():
    days = ["2026-10-16", "2026-10-19"]
    failed = pd.DataFrame(np.nan, index=pd.DatetimeIndex(days, name="Date"),
                          columns=["Open", "High", "Low", "Close", "Volume"])   # yf's empty_df
    df = _download({"AAPL": _bars(days, 100.0), "TSN": failed})

    out = snapshot_from_download(df, {"AAPL": "AAPL", "TSN": "TSN"}, date(2026, 10, 19))

    assert list(out) == ["AAPL"]
    assert list(out["AAPL"].columns) == ["ts", "open", "high", "low", "close"]
    assert out["AAPL"].open.tolist() == [100.0, 101.0]


def test_bars_after_the_session_are_dropped():
    df = _download({"BRK-B": _bars(["2026-10-16", "2026-10-19", "2026-10-20"], 400.0)})

    out = snapshot_from_download(df, {"BRK-B": "BRK.B"}, date(2026, 10, 19))

    assert out["BRK.B"].close.tolist() == [400.5, 401.5]


def test_a_ticker_with_no_bars_up_to_the_session_is_left_out():
    df = _download({"NEW": _bars(["2026-10-20"], 50.0)})

    assert snapshot_from_download(df, {"NEW": "NEW"}, date(2026, 10, 19)) == {}
