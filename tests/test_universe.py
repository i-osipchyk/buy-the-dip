"""Constituents from Wikipedia's "List of S&P 500 companies" (fixture: the page's table as
fetched on 2026-10-16)."""

from pathlib import Path

from btd.data.universe import parse_constituents

PAGE = (Path(__file__).parent / "fixtures" / "wikipedia_sp500_2026-10-16.html").read_text()


def test_reads_every_constituent_in_dot_style_with_both_share_classes():
    tickers = parse_constituents(PAGE)

    assert len(tickers) == 503
    assert len(set(tickers)) == 503
    assert {"AAPL", "BRK.B", "BF.B", "GOOG", "GOOGL", "FOX", "FOXA", "NWS", "NWSA"} <= set(tickers)
