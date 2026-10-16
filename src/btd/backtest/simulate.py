"""The backtest: a daily loop around the live core.plan() with the Hermes fill rules
(ARCHITECTURE §11): entry on a touch of L at min(open, L); target at max(open, T) from the day
after entry; next-open exits at the open; everything still open is closed at the last close.

Per session d, in order (as hermes/research/dip_buy/dip_study.py):
  1. mark equity at the previous close (sizing input of last evening's plan, already applied);
  2. sell last evening's flagged exits at d's open;
  3. fill last evening's entry orders;
  4. intraday targets for positions held >= 1 session;
  5. evening: plan() on d's close -> flags, targets and orders for d+1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import pandas as pd

from btd.core import Entry, Holding, plan

from .membership import Membership

# Hermes's names for exit reasons, so the trade lists compare directly
WHY = {"rebound": "close_gt_high", "time": "time", "removed": "index_exit"}


@dataclass(frozen=True)
class Config:
    start: date
    end: date
    cost_bp: float = 3.0              # per side
    capital: float = 100_000.0
    swap_annual: float = 0.0          # financing on open notional, per calendar day


@dataclass
class _Position:
    ticker: str
    shares: float
    entry: float
    entry_day: date
    entry_index: int
    sig_close: float
    sig_atr: float
    sig_volp: float
    sig_ret: float
    mae: float = 0.0
    mfe: float = 0.0
    target: float | None = None
    exit_reason: str | None = None


def _grid(panel: dict[str, pd.DataFrame], days: list[date]) -> dict[date, pd.DataFrame]:
    """Per session, a table indexed by ticker with the columns plan() reads. ``prev_high`` is the
    ticker's high on the previous *session* (NaN if it had no bar then), as in Hermes."""
    frames = []
    for ticker, d in panel.items():
        d = d.reindex(days)
        d["prev_high"] = d.high.shift(1)
        d["ticker"] = ticker
        frames.append(d.dropna(subset=["close"]))
    long = pd.concat(frames)
    return {cast(date, day): g.set_index("ticker") for day, g in long.groupby(level=0)}


def simulate(panel: dict[str, pd.DataFrame], membership: Membership,
             cfg: Config) -> tuple[pd.DataFrame, pd.Series]:
    """``panel``: ticker -> core.indicators() frame. Returns (trades in Hermes's columns,
    daily equity)."""
    all_days = sorted(set().union(*(d.index for d in panel.values())))
    days = [d for d in all_days if cfg.start <= d <= cfg.end]
    by_day = _grid(panel, days)
    cost = cfg.cost_bp / 1e4
    cash = cfg.capital
    positions: dict[str, _Position] = {}
    orders: list[Entry] = []
    signals: dict[str, dict[str, float]] = {}
    last_close: dict[str, float] = {}
    trades: list[dict[str, Any]] = []
    equity: list[tuple[date, float]] = []

    def close(p: _Position, day: date, px: float, why: str) -> None:
        nonlocal cash
        cash += p.shares * px * (1 - cost)
        positions.pop(p.ticker)
        trades.append({
            "ticker": p.ticker, "entry_date": p.entry_day, "exit_date": day, "entry": p.entry,
            "exit": px, "ret": (1 - cost) ** 2 * px / p.entry - 1, "why": why,
            "volp": p.sig_volp, "ret_sig": p.sig_ret,
            "depth_atr": (p.sig_close - p.entry) / max(p.sig_atr, 1e-9), "mae": p.mae,
            "mfe": p.mfe})

    for j, day in enumerate(days):
        today = by_day.get(day, pd.DataFrame())
        bars = cast(dict[str, dict[str, float]], today.to_dict("index"))
        if j > 0:
            gross = sum(p.shares * last_close[t] for t, p in positions.items())
            cash -= gross * cfg.swap_annual * (day - days[j - 1]).days / 365
        # 2. last evening's flagged exits, at today's open (the last close if no bar today)
        for p in [p for p in positions.values() if p.exit_reason]:
            px = bars[p.ticker]["open"] if p.ticker in bars else last_close[p.ticker]
            close(p, day, px, WHY[p.exit_reason or ""])
        # 3. last evening's entry orders
        for o in orders:
            if o.ticker not in bars:
                continue                                  # no bar: the order just doesn't fill
            bar = bars[o.ticker]
            if bar["low"] <= o.limit:
                px = min(bar["open"], o.limit)
                cash -= o.shares * px / (1 - cost)
                s = signals[o.ticker]
                positions[o.ticker] = _Position(o.ticker, o.shares, px, day, j, s["close"],
                                                s["atr5"], s["volpct"], s["ret"])
        # 4. intraday: excursions, and the target from the session after entry
        for p in list(positions.values()):
            if p.ticker not in bars:
                continue
            bar = bars[p.ticker]
            p.mae = min(p.mae, bar["low"] / p.entry - 1)
            p.mfe = max(p.mfe, bar["high"] / p.entry - 1)
            if j > p.entry_index and p.target is not None and bar["high"] >= p.target:
                close(p, day, max(bar["open"], p.target), "target")
        for t, bar in bars.items():
            last_close[t] = bar["close"]
        # 5. evening
        if j == len(days) - 1:
            for p in list(positions.values()):
                close(p, day, last_close[p.ticker], "end")
        else:
            members = membership.on(day)
            table = today.assign(member=today.index.isin(members))
            holdings = [Holding(p.ticker, p.shares, p.entry, j - p.entry_index)
                        for p in positions.values()]
            eq = cash + sum(p.shares * last_close[p.ticker] for p in positions.values())
            decided = plan(table, holdings, eq)
            for t, reason in decided.exits.items():
                positions[t].exit_reason = reason
            for t, target in decided.targets.items():
                positions[t].target = target
            orders = decided.entries
            signals = {c.ticker: {"close": c.close, "atr5": c.atr5, "volpct": c.volpct,
                                  "ret": c.ret} for c in decided.candidates}
        equity.append((day, cash + sum(p.shares * last_close[p.ticker]
                                       for p in positions.values())))
    columns = ["ticker", "entry_date", "exit_date", "entry", "exit", "ret", "why", "volp",
               "ret_sig", "depth_atr", "mae", "mfe"]
    return (pd.DataFrame(trades, columns=columns),
            pd.Series(dict(equity), name="equity", dtype=float))
