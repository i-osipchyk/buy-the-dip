"""Point-in-time index membership from a ``date,tickers`` CSV (sp500_history.csv, the file the
Hermes backtest used): on day d, the latest snapshot dated on or before d."""

from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Membership:
    dates: list[date]
    members: list[frozenset[str]]

    @classmethod
    def from_csv(cls, path: Path) -> Membership:
        dates, members = [], []
        with path.open() as f:
            for row in csv.DictReader(f):
                dates.append(date.fromisoformat(row["date"]))
                members.append(frozenset(t.strip() for t in row["tickers"].split(",")))
        return cls(dates, members)

    def on(self, day: date) -> frozenset[str]:
        i = bisect_right(self.dates, day) - 1
        return self.members[i] if i >= 0 else frozenset()
