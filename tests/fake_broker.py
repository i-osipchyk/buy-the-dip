"""In-memory stand-ins for the runs' boundaries: the broker (CTraderClient's interface), clock,
notifier, bar and constituents sources."""

from __future__ import annotations

import itertools
from datetime import datetime

from btd.broker import CTraderError, Deal, PendingOrder, Position, SymbolSpec

from bars import reference_bars


class FakeClock:
    def __init__(self, now: datetime):
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now


class FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    async def send(self, text):
        self.sent.append(text)


class FakeBroker:
    def __init__(self, names: dict[str, int], *, balance: float = 50_000.0, live: bool = False):
        self.names = names
        self._balance = balance
        self.live = live
        self.positions: dict[int, Position] = {}
        self.orders: dict[int, PendingOrder] = {}
        self.deal_list: list[Deal] = []
        self.placed: list[dict] = []            # every accepted placement, in order
        self.cancelled: list[int] = []
        self.amended: list[tuple[int, float]] = []
        self.closed: list[int] = []
        self.reject: dict[str, str] = {}        # clientOrderId -> error code
        self.fill_price: dict[int, float] = {}  # position id -> the price a market close fills at
        self.now = None                         # a FakeClock: stamps the deals of market closes
        self.calls: list[str] = []
        self._ids = itertools.count(1000)

    async def is_live(self):
        self.calls.append("is_live")
        return self.live

    async def balance(self):
        return self._balance

    async def symbol_names(self):
        self.calls.append("symbol_names")
        return dict(self.names)

    async def symbol_specs(self, symbol_ids):
        return {i: SymbolSpec(i, 2, 100, 10, 10) for i in symbol_ids}

    async def reconcile(self):
        self.calls.append("reconcile")
        return list(self.positions.values()), list(self.orders.values())

    async def deals(self, start, end):
        if start >= end:                          # as the real API (seen 2026-10-16)
            raise CTraderError("INCORRECT_BOUNDARIES", "Incorrect period boundaries")
        return [d for d in self.deal_list if start <= d.time <= end]

    async def place_limit_order(self, symbol_id, side, *, volume, limit_price, expiry, label,
                                client_order_id):
        if client_order_id in self.reject:
            raise CTraderError(self.reject[client_order_id])
        order_id = next(self._ids)
        self.orders[order_id] = PendingOrder(
            order_id=order_id, symbol_id=symbol_id, side=side, volume=volume, stop_price=0.0,
            stop_loss=None, label=label, client_order_id=client_order_id, expiry=expiry,
            limit_price=limit_price)
        self.placed.append({"symbol_id": symbol_id, "side": side, "volume": volume,
                            "limit": limit_price, "expiry": expiry, "label": label,
                            "client_order_id": client_order_id})
        return order_id

    async def cancel_order(self, order_id):
        self.orders.pop(order_id)
        self.cancelled.append(order_id)

    async def amend_take_profit(self, position_id, take_profit):
        p = self.positions[position_id]
        self.positions[position_id] = Position(**{**p.__dict__, "take_profit": take_profit})
        self.amended.append((position_id, take_profit))

    async def close_position(self, position_id, *, volume):
        if position_id not in self.positions:
            raise CTraderError("POSITION_NOT_FOUND")
        p = self.positions.pop(position_id)
        self.closed.append(position_id)
        price = self.fill_price.get(position_id, p.entry_price)
        when = self.now.now() if self.now else p.opened_at
        self.deal_list.append(Deal(
            deal_id=next(self._ids), order_id=next(self._ids), position_id=position_id,
            side="sell", volume=volume, price=price, time=when,
            commission=-0.1, closing=True, entry_price=p.entry_price,
            gross_profit=volume / 100 * (price - p.entry_price), swap=0.0,
            symbol_id=p.symbol_id))


class FakeBars:
    """The recorded reference bars, cut at the session (as a fetch that evening would see)."""

    def __init__(self, tickers=("META", "EXPE", "GLW", "CF")):
        self.tickers = tickers
        self.fetched: list[tuple[list[str], object]] = []
        self.fail = False

    def fetch(self, tickers, session):
        self.fetched.append((list(tickers), session))
        if self.fail:
            return {}
        from btd.data.bars import session_dates
        out = {}
        for t in tickers:
            if t in self.tickers:
                b = reference_bars(t)
                out[t] = b[session_dates(b) <= session].reset_index(drop=True)
        return out


FILLERS = [f"F{i:03d}" for i in range(496)]          # constituents the venue doesn't list


class FakeConstituents:
    def __init__(self, tickers=("META", "EXPE", "GLW", "CF")):
        self.tickers = list(tickers) + FILLERS

    def fetch(self):
        return list(self.tickers)
