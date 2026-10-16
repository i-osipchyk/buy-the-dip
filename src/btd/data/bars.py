"""The night's daily bars (ARCHITECTURE §4.1): a snapshot of ticker -> bars in the backtest's
format (``ts`` = the session's midnight in New York, in seconds; open/high/low/close)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

import pandas as pd

Snapshot = Mapping[str, pd.DataFrame]
MIN_COVERAGE = 0.98
NY = "America/New_York"


def session_dates(bars: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(bars.ts, unit="s", utc=True).dt.tz_convert(NY).dt.date


def has_session_bar(bars: pd.DataFrame | None, session: date) -> bool:
    if bars is None or bars.empty:
        return False
    last = bars.iloc[-1]
    return bool(session_dates(bars).iloc[-1] == session
                and last[["open", "high", "low", "close"]].notna().all())


def validate(snapshot: Snapshot, session: date, universe: Iterable[str],
             held: Iterable[str]) -> list[str]:
    """Problems that make the snapshot unusable for planning ``session`` (empty: valid)."""
    names = list(universe)
    complete = sum(has_session_bar(snapshot.get(t), session) for t in names)
    problems = []
    if complete < MIN_COVERAGE * len(names):
        problems.append(f"bars: {complete} of {len(names)} names have a complete {session} bar "
                        f"(need {MIN_COVERAGE:.0%})")
    problems += [f"bars: held {t} has no complete {session} bar" for t in sorted(held)
                 if not has_session_bar(snapshot.get(t), session)]
    return problems


MAX_CLOSE_DIFF_BP = 150
MAX_FLAGGED_SHARE = 0.05


@dataclass(frozen=True)
class CrossCheck:
    flagged: dict[str, float]     # ticker -> venue vs yfinance close, bp
    alert: str | None


def cross_check(closes: Mapping[str, float], venue_closes: Mapping[str, float]) -> CrossCheck:
    """yfinance's close against the venue's D1 close for the same session (SPIKE §4)."""
    common = [t for t in closes if t in venue_closes]
    diff = {t: (venue_closes[t] / closes[t] - 1) * 1e4 for t in common}
    flagged = {t: bp for t, bp in diff.items() if abs(bp) > MAX_CLOSE_DIFF_BP}
    alert = None
    if len(flagged) > MAX_FLAGGED_SHARE * len(common):
        alert = (f"bars: {len(flagged)} of {len(common)} closes differ from the venue's by "
                 f"> {MAX_CLOSE_DIFF_BP} bp")
    return CrossCheck(flagged, alert)
