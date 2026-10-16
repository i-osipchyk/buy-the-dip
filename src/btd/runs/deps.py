"""What a run needs from the outside world, injected so runs are testable offline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from ..broker import Deal, PendingOrder, Position, SymbolSpec
from ..calendar import Calendar
from ..data.bars import Snapshot
from ..store import Store


class Broker(Protocol):
    """The part of CTraderClient the runs use."""

    async def is_live(self) -> bool: ...

    async def balance(self) -> float: ...

    async def symbol_names(self) -> dict[str, int]: ...

    async def symbol_specs(self, symbol_ids: list[int]) -> dict[int, SymbolSpec]: ...

    async def reconcile(self) -> tuple[list[Position], list[PendingOrder]]: ...

    async def deals(self, start: datetime, end: datetime) -> list[Deal]: ...

    async def place_limit_order(self, symbol_id: int, side: str, *, volume: int,
                                limit_price: float, expiry: datetime, label: str,
                                client_order_id: str) -> int: ...

    async def cancel_order(self, order_id: int) -> None: ...

    async def amend_take_profit(self, position_id: int, take_profit: float) -> None: ...

    async def close_position(self, position_id: int, *, volume: int) -> None: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class Notifier(Protocol):
    async def send(self, text: str) -> None: ...


class BarSource(Protocol):
    def fetch(self, tickers: list[str], session: date) -> Snapshot: ...


class ConstituentsSource(Protocol):
    def fetch(self) -> list[str]: ...


@dataclass
class Deps:
    env: str                              # "dev" | "prod"
    broker: Broker
    store: Store
    notifier: Notifier
    clock: Clock
    bars: BarSource
    constituents: ConstituentsSource
    calendar: Calendar

    @property
    def label(self) -> str:
        return f"btd-{self.env}"
