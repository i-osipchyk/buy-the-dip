"""One evening's decisions (ARCHITECTURE §2.2-2.5): exits, targets and entries for day t+1.

Prices (L, T) are exact. Rounding to the venue's tick is the broker layer's job when it sends the
order: on the backtest's adjusted history (NFLX 2011 ~ $3) a cent is ~0.3% and would change
which targets are hit."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

SLOT = 0.10          # of equity per position
DEPTH = 0.9          # L = Close - DEPTH * ATR5
DROP = -0.03
VOL_MIN = 3.0
SHARE_STEP = 0.1     # the venue's volume step (and minimum)
SLOTS = 10
MIN_SLOT = 0.2       # skip an order smaller than this fraction of a full slot
TARGET_ATR = 0.5     # T = Close + TARGET_ATR * ATR5
MAX_HOLD = 10        # sessions


@dataclass(frozen=True)
class Holding:
    """An open btd position at the close of day t."""

    ticker: str
    shares: float
    entry_price: float
    held: int                     # sessions since the entry session (0 on the entry day)


@dataclass(frozen=True)
class Entry:
    ticker: str
    rank: int
    limit: float
    shares: float


@dataclass(frozen=True)
class Candidate:
    """A signal on day t, ordered or not; ``status`` is "ordered" or the skip reason."""

    ticker: str
    rank: int
    close: float
    atr5: float
    sma200: float
    ret: float
    volpct: float
    status: str


@dataclass(frozen=True)
class Plan:
    entries: list[Entry]
    candidates: list[Candidate]
    targets: dict[str, float]     # ticker -> the take-profit for session t+1
    exits: dict[str, str]         # ticker -> reason: sell at the open of t+1


def _floor_step(x: float) -> float:
    return math.floor(x / SHARE_STEP + 1e-9) * SHARE_STEP


def plan(day: pd.DataFrame, holdings: list[Holding], equity: float) -> Plan:
    """``day``: one row per ticker for day t (close, high, prev_high, atr5, sma200, ret, volpct,
    member), indexed by ticker."""
    rows: dict[str, dict[str, Any]] = {
        str(t): {str(k): v for k, v in r.items()}
        for t, r in zip(day.index, day.to_dict("records"), strict=True)}
    targets: dict[str, float] = {}
    exits: dict[str, str] = {}
    for h in holdings:
        if h.ticker not in rows:
            continue                       # no bar today (halt): no new decision, its TP stays
        r = rows[h.ticker]
        if r["close"] > r["prev_high"]:
            exits[h.ticker] = "rebound"
        elif h.held >= MAX_HOLD:
            exits[h.ticker] = "time"
        elif not r["member"]:
            exits[h.ticker] = "removed"
        else:
            targets[h.ticker] = r["close"] + TARGET_ATR * r["atr5"]
    held = {h.ticker for h in holdings} - set(exits)
    signals = sorted(
        (t for t, r in rows.items() if r["member"] and r["close"] > r["sma200"]
         and r["ret"] < DROP and r["volpct"] > VOL_MIN),
        key=lambda t: (-rows[t]["volpct"], t))
    ranked = [t for t in signals if t not in held]
    free = SLOTS - len(holdings) + len(exits)        # open exits are sold before entries fill
    # gross cap: what stays held (marked at the close) + tonight's orders <= equity
    room = equity - sum(h.shares * (rows[h.ticker]["close"] if h.ticker in rows else h.entry_price)
                        for h in holdings if h.ticker in held)
    entries, candidates = [], []
    for rank, t in enumerate(ranked, start=1):
        r = rows[t]
        status = "no_slot"
        if rank <= free:
            limit = r["close"] - DEPTH * r["atr5"]
            alloc = min(SLOT * equity, room)
            if alloc < MIN_SLOT * SLOT * equity:
                status = "cap_trim"
            elif (shares := round(_floor_step(alloc / limit), 1)) < SHARE_STEP:
                status = "min_size"
            else:
                entries.append(Entry(t, rank, limit, shares))
                room -= alloc
                status = "ordered"
        candidates.append(Candidate(t, rank, r["close"], r["atr5"], r["sma200"], r["ret"],
                                    r["volpct"], status))
    for t in signals:
        if t in held:
            r = rows[t]
            candidates.append(Candidate(t, 0, r["close"], r["atr5"], r["sma200"], r["ret"],
                                        r["volpct"], "held"))
    return Plan(entries, candidates, targets, exits)
