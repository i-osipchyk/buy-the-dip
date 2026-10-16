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


# --- build(): constituents ∩ venue, with sanity guards (ARCHITECTURE §4.2) --------------------

from btd.data.universe import build  # noqa: E402

SP = [f"T{i:03d}" for i in range(500)] + ["BRK.B", "BF.B", "NOTLISTED"]   # 503 names
VENUE = [f"T{i:03d}.US" for i in range(500)] + [
    "BRK.B.US", "BF-B.US", "T000.US-24", "T001.US_SB", "EURUSD", "EXTRA.US"]


def test_the_universe_is_the_constituents_the_venue_lists_mapped_to_venue_names():
    result = build(SP, VENUE, previous=None)

    assert result.alerts == []
    assert len(result.universe.venue) == 502
    assert result.universe.venue["BRK.B"] == "BRK.B.US"
    assert result.universe.venue["BF.B"] == "BF-B.US"
    assert "NOTLISTED" not in result.universe.venue and "EXTRA" not in result.universe.venue
    assert result.universe.constituents == SP


def test_an_implausible_count_keeps_the_previous_universe_and_alerts():
    previous = build(SP, VENUE, previous=None).universe

    result = build(SP[:400], VENUE, previous=previous)              # a half-broken page

    assert result.universe == previous
    assert result.alerts == ["universe: 400 constituents scraped (expected 495-510); "
                             "keeping the previous snapshot"]


def test_more_than_five_changes_keeps_the_previous_universe_and_alerts():
    previous = build(SP, VENUE, previous=None).universe
    renamed = [f"N{i:03d}" for i in range(6)] + SP[6:]               # 6 removed, 6 added

    result = build(renamed, VENUE, previous=previous)

    assert result.universe == previous
    assert result.alerts == ["universe: 12 changes since the previous snapshot (max 5); "
                             "keeping the previous snapshot"]


def test_up_to_five_changes_are_applied():
    previous = build(SP, VENUE, previous=None).universe
    renamed = ["N000", "N001"] + SP[2:]                               # 4 changes

    result = build(renamed, VENUE, previous=previous)

    assert result.alerts == []
    assert result.universe.constituents == renamed


def test_a_bad_first_scrape_with_nothing_to_fall_back_on_is_an_error():
    import pytest

    with pytest.raises(ValueError, match="400 constituents scraped"):
        build(SP[:400], VENUE, previous=None)
