"""Telegram message texts (ARCHITECTURE §9). Plain text."""

from __future__ import annotations

from datetime import date
from typing import Any


def alert_text(env: str, day: date, text: str) -> str:
    return f"ALERT [{env}] {day}: {text}"


def evening_summary(record: dict[str, Any]) -> str:
    """The evening's one message: also the daily sign of life."""
    ledger = record["ledger"]
    positions = record["positions"]
    lines = [f"[{record['env']}] {record['session']} evening",
             f"equity {ledger['equity']:,.0f} (drawdown {ledger['drawdown']:.1%}), "
             f"{len(positions)}/10 slots"]
    fills = record["fills"]
    lines.append("fills: " + (", ".join(
        f"{'sold' if f['closing'] else 'bought'} {f['position_id']} @ {f['price']:.2f}"
        for f in fills) if fills else "none"))
    for p in positions:
        if p["exit"]:
            lines.append(f"{p['ticker']} held {p['held']}: sell at the open ({p['exit']})")
        else:
            lines.append(f"{p['ticker']} held {p['held']}: target {p['target']:.2f}")
    placed = [o for o in record["orders"] if o["status"] == "placed"]
    if placed:
        lines.append("tonight: " + ", ".join(
            f"{o['ticker']} {o['shares']:.1f} @ {o['limit']:.2f}" for o in placed))
    return "\n".join(lines)
