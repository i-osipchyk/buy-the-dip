"""Pure strategy core (ARCHITECTURE §2): bars, universe, ledger, positions in; a Plan out.

No network, clock, env or AWS here. The backtest and the evening Lambda call the same plan()."""

from .indicators import indicators
from .plan import Entry, Holding, Plan, plan

__all__ = ["Entry", "Holding", "Plan", "indicators", "plan"]
