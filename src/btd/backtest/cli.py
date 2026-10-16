"""Backtest CLI (ARCHITECTURE §11): Hermes-format bars in, Hermes-format trades CSV out.

    uv run python -m btd.backtest --bars ~/dev/hermes/.hermes_cache/bars/yfinance \\
        --start 2023-01-01 --end 2026-10-14 --cost-bp 3 --tag holdout_c3

Bars: one ``<TICKER>_1d.parquet`` per ticker (``ts`` seconds, open/high/low/close), the format of
Hermes's yfinance cache, so both sides can read the same files. Only tickers that were ever index
members are loaded (the cache also holds FX pairs etc.).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from btd.core import indicators

from .membership import Membership
from .simulate import Config, simulate

ROOT = Path(__file__).resolve().parents[3]


def load_panel(bars: Path, tickers: frozenset[str]) -> dict[str, pd.DataFrame]:
    panel = {}
    for path in sorted(bars.glob("*_1d.parquet")):
        ticker = path.name.removesuffix("_1d.parquet")
        if ticker not in tickers:
            continue
        frame = indicators(pd.read_parquet(path))
        if frame is not None:
            panel[ticker] = frame
    return panel


def load_venue(path: Path) -> frozenset[str]:
    """One ticker per line (a header line "0" or "ticker" is ignored)."""
    lines = (line.strip() for line in path.read_text().splitlines())
    return frozenset(t for t in lines if t and t not in {"0", "ticker"})


def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m btd.backtest")
    ap.add_argument("--bars", type=Path, required=True)
    ap.add_argument("--membership", type=Path, default=ROOT / "sp500_history.csv")
    ap.add_argument("--venue", type=Path, help="restrict to these tickers (one per line)")
    ap.add_argument("--start", type=date.fromisoformat, required=True)
    ap.add_argument("--end", type=date.fromisoformat, required=True)
    ap.add_argument("--cost-bp", type=float, default=3.0)
    ap.add_argument("--capital", type=float, default=100_000.0)
    ap.add_argument("--swap-annual", type=float, default=0.0)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "local" / "backtest")
    a = ap.parse_args(argv)

    membership = Membership.from_csv(a.membership)
    tickers = frozenset().union(*membership.members)
    if a.venue:
        tickers &= load_venue(a.venue)
    panel = load_panel(a.bars, tickers)
    trades, equity = simulate(panel, membership, Config(
        start=a.start, end=a.end, cost_bp=a.cost_bp, capital=a.capital,
        swap_annual=a.swap_annual))
    a.out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(a.out / f"trades_{a.tag}.csv", index=False)
    equity.rename_axis("date").to_csv(a.out / f"equity_{a.tag}.csv")
    print(f"{len(panel)} tickers, {len(trades)} trades, mean {trades.ret.mean():+.3%}, "
          f"equity {equity.iloc[0]:,.0f} -> {equity.iloc[-1]:,.0f}; written to {a.out}",
          file=sys.stderr)
