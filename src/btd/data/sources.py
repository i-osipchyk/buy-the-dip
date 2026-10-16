"""The network sources the evening run reads (not unit-tested: thin wrappers)."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

from .bars import Snapshot
from .tickers import to_yfinance
from .universe import WIKIPEDIA_URL, parse_constituents

NY = ZoneInfo("America/New_York")
USER_AGENT = "buy-the-dip/0.1 (+https://github.com/i-osipchyk/buy-the-dip)"
HISTORY = "15mo"                  # ~315 sessions: SMA200 and the 220-row minimum, with room


class YFinanceSource:
    """Fully adjusted (auto_adjust) daily bars, re-downloaded every night: each dividend
    re-bases the adjusted history, so bars are never appended (ARCHITECTURE §4.1)."""

    def fetch(self, tickers: list[str], session: date) -> Snapshot:
        import yfinance as yf

        yf.set_tz_cache_location("/tmp/yfinance")      # Lambda's filesystem is read-only
        symbols = {to_yfinance(t): t for t in tickers}
        df = yf.download(list(symbols), period=HISTORY, interval="1d", auto_adjust=True,
                         group_by="ticker", threads=True, progress=False)
        out = {}
        got = set(df.columns.get_level_values(0)) if len(df) else set()
        for ysym, ticker in symbols.items():
            if ysym not in got:
                continue
            d = df[ysym].dropna(how="all")
            d = d[[day.date() <= session for day in d.index]]
            ts = [int(datetime.combine(day.date(), time(0), NY).timestamp()) for day in d.index]
            out[ticker] = pd.DataFrame({"ts": ts, "open": d.Open.values, "high": d.High.values,
                                        "low": d.Low.values, "close": d.Close.values})
        return out


class WikipediaConstituents:
    def fetch(self) -> list[str]:
        page = httpx.get(WIKIPEDIA_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
        page.raise_for_status()
        return parse_constituents(page.text)
