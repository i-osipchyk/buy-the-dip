"""The trading universe: S&P 500 constituents ∩ venue symbols (ARCHITECTURE §4.2)."""

from __future__ import annotations

from lxml import html

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def parse_constituents(page: str) -> list[str]:
    """Tickers from the page's ``constituents`` table, in its order, canonical dot style."""
    cells = html.fromstring(page).cssselect("table#constituents tr > td:first-child")
    return [html.tostring(cell, method="text", encoding="unicode").strip() for cell in cells]
