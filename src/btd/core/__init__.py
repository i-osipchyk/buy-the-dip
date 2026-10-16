"""Pure strategy core (ARCHITECTURE §2): bars, universe, ledger, positions, calendar in; a Plan out.

No network, clock, env or AWS here. The backtest and the evening Lambda call the same plan()."""
