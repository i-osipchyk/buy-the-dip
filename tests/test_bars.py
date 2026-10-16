"""Validating the night's bar snapshot before planning (ARCHITECTURE §4.1)."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pandas as pd

from btd.data.bars import validate

NY = ZoneInfo("America/New_York")
SESSION = date(2026, 10, 15)


def _bars(*days: date, close: float = 100.0) -> pd.DataFrame:
    ts = [int(datetime.combine(d, time(0), NY).timestamp()) for d in days]
    return pd.DataFrame({"ts": ts, "open": 100.0, "high": 101.0, "low": 99.0, "close": close})


UNIVERSE = [f"T{i:03d}" for i in range(100)]


def test_a_snapshot_with_every_name_on_the_session_is_valid():
    snapshot = {t: _bars(date(2026, 10, 14), SESSION) for t in UNIVERSE}

    assert validate(snapshot, SESSION, UNIVERSE, held={"T001"}) == []


def test_too_few_names_with_a_complete_session_bar_is_invalid():
    snapshot = {t: _bars(date(2026, 10, 14), SESSION) for t in UNIVERSE[:97]}
    snapshot["T097"] = _bars(date(2026, 10, 14))                       # stale: no session bar
    nan = _bars(date(2026, 10, 14), SESSION)
    nan.loc[1, "close"] = float("nan")
    snapshot["T098"] = nan                                              # T099 missing entirely

    assert validate(snapshot, SESSION, UNIVERSE, held=set()) == [
        "bars: 97 of 100 names have a complete 2026-10-15 bar (need 98%)"]


def test_a_held_name_without_its_session_bar_is_invalid_even_with_good_coverage():
    snapshot = {t: _bars(date(2026, 10, 14), SESSION) for t in UNIVERSE}
    snapshot["T005"] = _bars(date(2026, 10, 14))

    assert validate(snapshot, SESSION, UNIVERSE, held={"T005", "T006"}) == [
        "bars: held T005 has no complete 2026-10-15 bar"]


def test_closes_far_from_the_venues_are_flagged_and_many_of_them_alert():
    from btd.data.bars import cross_check
    yahoo = {f"T{i:03d}": 100.0 for i in range(100)}
    venue = dict(yahoo) | {"T000": 98.4, "T001": 101.0}     # -160 bp (flagged), +100 bp (fine)

    few = cross_check(yahoo, venue)
    assert (list(few.flagged), few.alert) == (["T000"], None)

    many = cross_check(yahoo, venue | {f"T{i:03d}": 97.0 for i in range(2, 8)})   # 7 flagged
    assert many.alert == "bars: 7 of 100 closes differ from the venue's by > 150 bp"
