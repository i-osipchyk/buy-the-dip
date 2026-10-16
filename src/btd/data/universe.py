"""The trading universe: S&P 500 constituents ∩ venue symbols (ARCHITECTURE §4.2)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from lxml import html

from .tickers import from_venue

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
MIN_CONSTITUENTS, MAX_CONSTITUENTS = 495, 510
MAX_CHANGES = 5


def parse_constituents(page: str) -> list[str]:
    """Tickers from the page's ``constituents`` table, in its order, canonical dot style."""
    cells = html.fromstring(page).cssselect("table#constituents tr > td:first-child")
    return [html.tostring(cell, method="text", encoding="unicode").strip() for cell in cells]


@dataclass(frozen=True)
class Universe:
    constituents: list[str]       # canonical tickers, as scraped
    venue: dict[str, str]         # the tradable universe: canonical ticker -> venue symbol name


@dataclass(frozen=True)
class BuildResult:
    universe: Universe
    alerts: list[str]


def build(constituents: list[str], venue_names: Iterable[str],
          previous: Universe | None) -> BuildResult:
    """Constituents ∩ venue shares, with the canonical -> venue name map from the venue list.
    An implausible scrape (count, or too many changes) keeps ``previous`` and alerts."""
    keep = "keeping the previous snapshot"
    if not MIN_CONSTITUENTS <= len(constituents) <= MAX_CONSTITUENTS:
        problem = (f"{len(constituents)} constituents scraped "
                   f"(expected {MIN_CONSTITUENTS}-{MAX_CONSTITUENTS})")
        return _fallback(previous, f"universe: {problem}; {keep}")
    if previous is not None:
        changes = len(set(constituents) ^ set(previous.constituents))
        if changes > MAX_CHANGES:
            problem = f"{changes} changes since the previous snapshot (max {MAX_CHANGES})"
            return _fallback(previous, f"universe: {problem}; {keep}")
    on_venue = {}
    for name in venue_names:
        ticker = from_venue(name)
        if ticker is not None:
            on_venue[ticker] = name
    venue = {t: on_venue[t] for t in constituents if t in on_venue}
    return BuildResult(Universe(list(constituents), venue), [])


def _fallback(previous: Universe | None, alert: str) -> BuildResult:
    if previous is None:
        raise ValueError(alert.replace("; keeping the previous snapshot", "; no previous snapshot"))
    return BuildResult(previous, [alert])
