"""cTrader Open API access (ARCHITECTURE §6.4). The client is copied from gtb and extended."""

from .client import (
    DEMO_HOST,
    LIVE_HOST,
    Bar,
    CTraderClient,
    CTraderError,
    Deal,
    PendingOrder,
    Position,
    SymbolSpec,
)

__all__ = [
    "DEMO_HOST", "LIVE_HOST", "Bar", "CTraderClient", "CTraderError", "Deal", "PendingOrder",
    "Position", "SymbolSpec",
]
