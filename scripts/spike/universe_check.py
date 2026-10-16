"""Spike item 5: Wikipedia constituents ∩ venue symbols, against Hermes's list of 478."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from _conn import OUT

from btd.data.tickers import from_venue
from btd.data.universe import parse_constituents

HERMES = Path.home() / "dev/hermes/research/output/dip_buy/pepperstone_sp500_available.csv"


def main() -> None:
    constituents = parse_constituents((OUT / "sp500_wiki.html").read_text())
    venue = {}
    for name in json.loads((OUT / "symbols.json").read_text()):
        ticker = from_venue(name)
        if ticker is not None:
            venue[ticker] = name
    universe = sorted(t for t in constituents if t in venue)
    missing = sorted(t for t in constituents if t not in venue)
    with HERMES.open() as f:
        hermes = {row[0] for row in csv.reader(f)} - {"0"}
    print(f"constituents {len(constituents)}, venue shares {len(venue)}, universe {len(universe)}")
    print(f"not on venue ({len(missing)}): {' '.join(missing)}")
    print(f"in btd not Hermes: {sorted(set(universe) - hermes)}")
    print(f"in Hermes not btd: {sorted(hermes - set(universe))}")
    print("odd names:", {t: venue[t] for t in universe if "." in t})
    (OUT / "universe.json").write_text(json.dumps({t: venue[t] for t in universe}, indent=1))


if __name__ == "__main__":
    main()
