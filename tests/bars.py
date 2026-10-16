"""Test helper: the recorded reference bars (tests/fixtures/bars/README.md)."""

from pathlib import Path

import pandas as pd

BARS = Path(__file__).parent / "fixtures" / "bars"


def reference_bars(ticker: str) -> pd.DataFrame:
    return pd.read_parquet(BARS / f"{ticker}_1d.parquet")
