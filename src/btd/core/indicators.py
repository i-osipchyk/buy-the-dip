"""Per-ticker daily indicators (ARCHITECTURE §2.1), exactly as the Hermes backtest computes them:
over the ticker's own rows, simple (not Wilder) ATR5."""

from __future__ import annotations

import pandas as pd

MIN_ROWS = 220

def indicators(bars: pd.DataFrame) -> pd.DataFrame | None:
    """Bars (``ts`` = the session's midnight in New York, in seconds; open/high/low/close) ->
    a frame indexed by session date with OHLC, ``atr5``, ``sma200``, ``ret`` and ``volpct``.
    None when fewer than MIN_ROWS usable rows remain (the ticker is excluded)."""
    ny = pd.to_datetime(bars.ts, unit="s", utc=True).dt.tz_convert("America/New_York")
    d = bars[["open", "high", "low", "close"]].astype(float)
    d.index = pd.Index(ny.dt.date, name="date")
    d = d[~d.index.duplicated(keep="last")]
    d = d[(d > 0).all(axis=1)]
    if len(d) < MIN_ROWS:
        return None
    prev_close = d.close.shift(1)
    tr = pd.concat([d.high - d.low, (d.high - prev_close).abs(), (d.low - prev_close).abs()],
                   axis=1).max(axis=1)
    d["atr5"] = tr.rolling(5).mean()
    d["sma200"] = d.close.rolling(200).mean()
    d["ret"] = d.close / prev_close - 1
    d["volpct"] = 100 * d.atr5 / d.close
    return d
