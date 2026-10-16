"""The virtual btd ledger on the shared account (ARCHITECTURE §7), from broker facts only.

Deals carry no label, so they are attributed through ``btd_positions``: the ids of every position
with our label that a run has seen (each btd position is open at least one evening)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .broker import Deal, Position

VOLUME_PER_SHARE = 100           # the Open API's volume is in 1/100 share


@dataclass(frozen=True)
class Ledger:
    equity: float
    realized: float               # closed P&L + every commission and closed swap since genesis
    unrealized: float             # open positions marked at the close, plus accrued swap


def compute(start_capital: float, deals: Iterable[Deal], positions: Iterable[Position], *,
            marks: Mapping[int, float], btd_positions: set[int]) -> Ledger:
    """``deals`` since genesis (any label), ``positions`` open btd positions, ``marks`` the
    session close per open position id."""
    realized = 0.0
    for d in deals:
        if d.position_id not in btd_positions:
            continue
        realized += d.commission + (d.gross_profit or 0.0) + (d.swap or 0.0)
    unrealized = sum(p.volume / VOLUME_PER_SHARE * (marks[p.position_id] - p.entry_price) + p.swap
                     for p in positions)
    return Ledger(start_capital + realized + unrealized, realized, unrealized)
