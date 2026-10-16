"""The backtest CLI: Hermes-format bars in, Hermes-format trades CSV out."""

from pathlib import Path

from btd.backtest.cli import main

FIXTURES = Path(__file__).parent / "fixtures"
HERMES_HEADER = "ticker,entry_date,exit_date,entry,exit,ret,why,volp,ret_sig,depth_atr,mae,mfe"


def test_writes_the_trades_in_hermes_columns(tmp_path):
    main(["--bars", str(FIXTURES / "bars"), "--membership",
          str(FIXTURES / "membership_reference.csv"), "--start", "2026-09-01", "--end",
          "2026-10-14", "--cost-bp", "3", "--tag", "ref", "--out", str(tmp_path)])

    lines = (tmp_path / "trades_ref.csv").read_text().splitlines()
    assert lines[0] == HERMES_HEADER
    meta = next(line.split(",") for line in lines if line.startswith("META,2026-09-28,"))
    assert meta[2] == "2026-09-29"
    assert (round(float(meta[3]), 2), round(float(meta[4]), 2)) == (713.92, 731.71)
    assert (tmp_path / "equity_ref.csv").exists()
