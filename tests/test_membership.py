"""Point-in-time index membership from a ``date,tickers`` CSV (the format of sp500_history.csv)."""

from datetime import date
from pathlib import Path

from btd.backtest import Membership

CSV = Path(__file__).parent / "fixtures" / "membership.csv"


def test_membership_on_a_day_is_the_latest_snapshot_on_or_before_it():
    m = Membership.from_csv(CSV)

    assert m.on(date(2026, 1, 1)) == frozenset()                      # before the first
    assert m.on(date(2026, 1, 2)) == {"AAPL", "BRK.B", "OLD"}
    assert m.on(date(2026, 3, 19)) == {"AAPL", "BRK.B", "OLD"}
    assert m.on(date(2026, 3, 20)) == {"AAPL", "BRK.B", "NEW"}
    assert m.on(date(2026, 12, 31)) == {"AAPL", "BRK.B", "NEW"}       # carried forward
