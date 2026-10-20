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
    if "total_pnl" in ledger:                   # records from before 2026-10-20 lack it
        start = ledger["equity"] - ledger["total_pnl"]
        base = ledger["equity"] - ledger["day_pnl"]
        since = f"since {ledger['day_pnl_since']}" if ledger["day_pnl_since"] else "today"
        lines.append(f"P&L {since} {_money(ledger['day_pnl'])} ({ledger['day_pnl'] / base:+.2%}), "
                     f"total {_money(ledger['total_pnl'])} ({ledger['total_pnl'] / start:+.2%})")
    fills = record["fills"]
    lines.append("fills: " + (", ".join(_fill(f) for f in fills) if fills else "none"))
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


def _money(x: float) -> str:
    return f"{x:+,.2f}"


def _fill(f: dict[str, Any]) -> str:
    what = f.get("ticker") or f"position {f['position_id']}"
    text = f"{'sold' if f['closing'] else 'bought'} {what} {f['volume'] / 100:g} @ {f['price']:.2f}"
    return text + (f" ({_money(f['pnl'])})" if f.get("pnl") is not None else "")
