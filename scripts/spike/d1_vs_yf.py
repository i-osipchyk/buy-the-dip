"""Spike item 4: Pepperstone D1 trendbars against yfinance raw (unadjusted) daily bars.

Checks which New York date each D1 bar covers (its open time), and the close difference."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from _conn import OUT, demo_client

from btd.data.tickers import to_yfinance

NY = ZoneInfo("America/New_York")
FIXED = ["META", "EXPE", "GLW", "CF", "BRK.B", "BF.B", "AAPL", "NVDA", "CRWD", "XOM"]


async def venue_bars(tickers: dict[str, str]) -> pd.DataFrame:
    end = datetime.now(UTC)
    start = end - timedelta(days=70)
    rows = []
    async with demo_client() as client:
        names = await client.symbol_names()
        for ticker, name in tickers.items():
            for b in await client.trendbars(names[name], "D1", start, end):
                rows.append({"ticker": ticker, "open_utc": b.ts, "v_open": b.open,
                             "v_high": b.high, "v_low": b.low, "v_close": b.close})
    return pd.DataFrame(rows)


def main() -> None:
    universe: dict[str, str] = json.loads((OUT / "universe.json").read_text())
    rng = random.Random(16)
    sample = FIXED + rng.sample(sorted(set(universe) - set(FIXED)), 30)
    v = asyncio.run(venue_bars({t: universe[t] for t in sample}))
    v["open_ny"] = v.open_utc.dt.tz_convert(NY)
    print("D1 open times (NY):", v.open_ny.dt.strftime("%a %H:%M").value_counts().head(5).to_dict())
    # a D1 bar opens at 17:00 New York the evening before the session it holds
    v["date"] = (v.open_ny + pd.Timedelta(hours=7)).dt.date
    y = yf.download([to_yfinance(t) for t in sample], period="4mo", interval="1d",
                    auto_adjust=False, group_by="ticker", progress=False)
    rows = []
    for t in sample:
        d = y[to_yfinance(t)].dropna(how="all")
        rows.append(pd.DataFrame({"ticker": t, "date": d.index.date, "y_open": d.Open.values,
                                  "y_high": d.High.values, "y_low": d.Low.values,
                                  "y_close": d.Close.values}))
    m = v.merge(pd.concat(rows), on=["ticker", "date"], how="inner")
    for k in ("open", "high", "low", "close"):
        m[f"d_{k}_bp"] = (m[f"v_{k}"] / m[f"y_{k}"] - 1) * 1e4
    print(f"matched bars {len(m)} of venue {len(v)}")
    print(m[[c for c in m if c.startswith("d_")]].describe(percentiles=[.05, .5, .95]).round(2))
    worst = m.reindex(m.d_close_bp.abs().sort_values(ascending=False).index).head(8)
    print(worst[["ticker", "date", "v_close", "y_close", "d_close_bp"]].to_string(index=False))
    m.to_parquet(OUT / "d1_vs_yf.parquet")


if __name__ == "__main__":
    main()
