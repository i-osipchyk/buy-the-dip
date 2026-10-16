"""Ticker forms (ARCHITECTURE §4.2). Canonical is S&P dot style (``BRK.B``)."""

from __future__ import annotations

VENUE_SUFFIX = ".US"


def from_venue(name: str) -> str | None:
    """Venue symbol name -> canonical ticker, or None for anything but a regular-session US share
    (``-24`` extended hours, ``-PERP``, ``_SB*`` spread bets, FX, ...)."""
    if not name.endswith(VENUE_SUFFIX):
        return None
    return name.removesuffix(VENUE_SUFFIX).replace("-", ".")   # the venue has BRK.B.US but BF-B.US


def to_yfinance(ticker: str) -> str:
    """Canonical ticker -> Yahoo symbol (share classes with a dash: BRK-B)."""
    return ticker.replace(".", "-")
