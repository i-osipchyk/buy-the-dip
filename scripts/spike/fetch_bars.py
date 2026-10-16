"""Spike items 1 and 2: download the universe from yfinance (auto_adjust), time it, and keep a
tagged snapshot so closes fetched at different times can be compared (compare_closes.py).

    uv run python scripts/spike/fetch_bars.py --tag 1630
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from _conn import OUT

from btd.data.tickers import to_yfinance

NY = ZoneInfo("America/New_York")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--period", default="15mo")          # about 315 sessions
    a = ap.parse_args()
    universe = sorted(json.loads((OUT / "universe.json").read_text()))
    symbols = {to_yfinance(t): t for t in universe}
    started = time.monotonic()
    df = yf.download(list(symbols), period=a.period, interval="1d", auto_adjust=True,
                     group_by="ticker", threads=True, progress=False)
    took = time.monotonic() - started
    fetched_at = datetime.now(NY)
    rows = []
    for ysym, ticker in symbols.items():
        if ysym not in df.columns.get_level_values(0):
            continue
        d = df[ysym].dropna(how="all")
        d = d.assign(ticker=ticker, date=d.index.date)
        rows.append(d.reset_index(drop=True))
    bars = pd.concat(rows, ignore_index=True)
    last = bars.groupby("ticker").date.max()
    newest = last.max()
    complete = bars[bars.date == newest].dropna(subset=["Open", "High", "Low", "Close"])
    missing = sorted(set(universe) - set(bars.ticker))
    stale = sorted(last[last < newest].index)
    print(f"{fetched_at:%Y-%m-%d %H:%M %Z}: {took:.1f}s, {bars.ticker.nunique()}/{len(universe)} "
          f"tickers, newest bar {newest}, complete on it {len(complete)}, "
          f"rows/ticker median {bars.groupby('ticker').size().median():.0f}")
    print(f"missing: {missing}\nstale (last bar < {newest}): {stale}")
    OUT.mkdir(parents=True, exist_ok=True)
    bars.attrs = {}
    bars.to_parquet(OUT / f"bars_{a.tag}.parquet")
    log = OUT / "fetch_log.jsonl"
    with log.open("a") as f:
        f.write(json.dumps({"tag": a.tag, "at": fetched_at.isoformat(), "seconds": round(took, 1),
                            "tickers": int(bars.ticker.nunique()), "universe": len(universe),
                            "newest": str(newest), "complete": len(complete),
                            "missing": missing, "stale": stale}) + "\n")


if __name__ == "__main__":
    main()
