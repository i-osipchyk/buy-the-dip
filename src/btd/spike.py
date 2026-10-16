"""Spike item 1 (throwaway, removed after Phase 1): does a Lambda in AWS reach Wikipedia and
yfinance reliably? Read-only: no broker, no orders. Results go to the function's log."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import yfinance as yf

from btd.data.tickers import to_yfinance
from btd.data.universe import WIKIPEDIA_URL, parse_constituents

USER_AGENT = "buy-the-dip/0.1 (+https://github.com/i-osipchyk/buy-the-dip)"
NY = ZoneInfo("America/New_York")
logger = logging.getLogger(__name__)


def fetch() -> dict[str, Any]:
    out: dict[str, Any] = {"at": datetime.now(NY).isoformat()}
    started = time.monotonic()
    page = httpx.get(WIKIPEDIA_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    out["wikipedia_status"] = page.status_code
    tickers = parse_constituents(page.text) if page.status_code == 200 else []
    out["constituents"] = len(tickers)
    out["wikipedia_seconds"] = round(time.monotonic() - started, 1)
    yf.set_tz_cache_location("/tmp/yfinance")          # the Lambda filesystem is read-only
    started = time.monotonic()
    df = yf.download([to_yfinance(t) for t in tickers], period="15mo", interval="1d",
                     auto_adjust=True, group_by="ticker", threads=True, progress=False)
    out["yfinance_seconds"] = round(time.monotonic() - started, 1)
    got = set(df.columns.get_level_values(0)) if len(df) else set()
    last = {s: df[s].Close.last_valid_index() for s in got}
    newest = max((d for d in last.values() if d is not None), default=None)
    out["tickers_with_data"] = sum(d is not None for d in last.values())
    out["newest_bar"] = str(newest.date()) if newest is not None else None
    out["complete_on_newest"] = sum(d == newest for d in last.values())
    out["missing"] = sorted(to_yfinance(t) for t in tickers
                            if last.get(to_yfinance(t)) is None)[:50]
    logger.info("SPIKE %s", json.dumps(out))
    return out
