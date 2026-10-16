"""Spike item 2: compare the bars of one session fetched at different times.

    uv run python scripts/spike/compare_closes.py --date 2026-10-16 1630 2000 next
"""

from __future__ import annotations

import argparse
from datetime import date

import pandas as pd
from _conn import OUT


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=date.fromisoformat, required=True)
    ap.add_argument("tags", nargs="+", help="fetch tags, earliest first; the last is the truth")
    a = ap.parse_args()
    snaps = {}
    for tag in a.tags:
        b = pd.read_parquet(OUT / f"bars_{tag}.parquet")
        snaps[tag] = b[b.date == a.date].set_index("ticker")[["Open", "High", "Low", "Close"]]
    truth_tag = a.tags[-1]
    truth = snaps[truth_tag]
    for tag in a.tags[:-1]:
        s = snaps[tag].reindex(truth.index)
        have = s.Close.notna().sum()
        print(f"{tag} vs {truth_tag} on {a.date}: {have}/{len(truth)} have the bar")
        for col in ("Open", "High", "Low", "Close"):
            diff = (s[col] - truth[col]).abs()
            print(f"  {col:5s}: differ by >= 1 cent in {int((diff >= 0.005).sum())} names, "
                  f"max {diff.max():.2f}")
        bad = (s.Close - truth.Close).abs().sort_values(ascending=False).head(5)
        print("  worst closes:", {t: (round(s.Close[t], 2), round(truth.Close[t], 2))
                                   for t in bad.index if bad[t] >= 0.005})


if __name__ == "__main__":
    main()
