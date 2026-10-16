"""The virtual btd ledger on the shared account (ARCHITECTURE §7). Money in USD."""

from datetime import UTC, datetime

import pytest

from btd.broker import Deal, Position
from btd.ledger import compute

T = datetime(2026, 9, 28, 14, 31, tzinfo=UTC)


def _deal(deal_id: int, position_id: int, *, commission: float, closing: bool = False,
          gross: float | None = None, swap: float | None = None) -> Deal:
    return Deal(deal_id=deal_id, order_id=deal_id + 100, position_id=position_id, side="buy",
                volume=700, price=713.92, time=T, commission=commission, closing=closing,
                entry_price=713.92 if closing else None, gross_profit=gross, swap=swap)


def test_a_closed_round_trip_and_an_open_position_move_equity():
    deals = [_deal(1, 5501, commission=-0.14),
             _deal(2, 5501, commission=-0.14, closing=True, gross=124.53, swap=-0.87),
             _deal(3, 5502, commission=-0.20)]                      # 5502 is still open
    open_ = Position(position_id=5502, symbol_id=333, side="buy", volume=1000, entry_price=250.0,
                     stop_loss=None, label="btd-dev", opened_at=T, swap=-0.50)

    ledger = compute(50_000.0, deals, [open_], marks={5502: 252.0}, btd_positions={5501, 5502})

    # realized: 124.53 - 0.87 - 0.14 - 0.14 - 0.20 = 123.18
    # unrealized: 10 shares x (252.00 - 250.00) - 0.50 = 19.50
    assert ledger.realized == pytest.approx(123.18)
    assert ledger.unrealized == pytest.approx(19.50)
    assert ledger.equity == pytest.approx(50_142.68)


def test_deals_of_the_other_strategys_positions_do_not_count():
    foreign = [_deal(9, 777, commission=-3.01),
               _deal(10, 777, commission=-3.01, closing=True, gross=-950.0, swap=-4.0)]

    ledger = compute(50_000.0, foreign, [], marks={}, btd_positions={5501})

    assert ledger.equity == 50_000.0
