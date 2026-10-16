"""Ticker forms: canonical S&P dot style (BRK.B), yfinance (BRK-B), venue names from the real
Pepperstone list (data pulled 2026-10-16: BRK.B.US but BF-B.US)."""

from btd.data.tickers import from_venue, to_yfinance


def test_a_plain_venue_share_maps_to_its_ticker():
    assert from_venue("AAPL.US") == "AAPL"


def test_extended_hours_spread_bet_perpetual_and_non_share_symbols_are_not_ours():
    for name in ("AAPL.US-24", "AAPL.US-24_SB", "AAPL.US-24_SBE", "AAPL.US_SB", "AAPL.US_SB2",
                 "AAPL.US_SBE", "GOOGL.US-PERP", "GOOGL.US-PERP_SB", "EURUSD", "XAUUSD"):
        assert from_venue(name) is None, name


def test_share_classes_map_to_dot_style_whichever_separator_the_venue_uses():
    assert from_venue("BRK.B.US") == "BRK.B"
    assert from_venue("BF-B.US") == "BF.B"


def test_yfinance_spells_share_classes_with_a_dash():
    assert to_yfinance("BRK.B") == "BRK-B"
    assert to_yfinance("BF.B") == "BF-B"
    assert to_yfinance("AAPL") == "AAPL"
