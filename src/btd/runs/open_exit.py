"""The open-exit run (ARCHITECTURE §5, 09:35 New York): market-close the positions the previous
evening flagged (rebound, time, removal). cTrader has no market-on-open order and rejects market
orders while closed (SPIKE §3), so this runs a few minutes after the open."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from .deps import Deps
from .evening import key
from .guards import wrong_account


async def open_exit(deps: Deps) -> None:
    now = deps.clock.now()
    session = now.date()
    if not deps.calendar.is_session(session):
        return
    done = key(deps.env, "open_exits", session)
    if (deps.store.get_json(done) or {}).get("complete") or await wrong_account(deps, session):
        return
    record = deps.store.get_json(key(deps.env, "records", deps.calendar.previous_session(session)))
    flagged = [p for p in (record or {}).get("positions", []) if p["exit"]]
    positions, _ = await deps.broker.reconcile()
    open_ids = {p.position_id: p for p in positions if p.label == deps.label}
    exits: list[dict[str, Any]] = []
    for f in flagged:
        exit_ = {"position_id": f["position_id"], "ticker": f["ticker"], "reason": f["exit"],
                 "result": "already closed", "price": None}
        p = open_ids.get(f["position_id"])
        if p is not None:
            await deps.broker.close_position(p.position_id, volume=p.volume)
            exit_["result"] = "closed"
        exits.append(exit_)
    deals = await deps.broker.deals(datetime.combine(session, time(0), now.tzinfo),
                                    deps.clock.now())
    sold = {d.position_id: d.price for d in deals if d.closing}
    for e in exits:
        if e["result"] == "closed":
            e["price"] = sold.get(e["position_id"])
    deps.store.put_json(done,
                        {"session": session.isoformat(), "complete": True, "exits": exits})
    if exits:
        lines = [f"[{deps.env}] {session} open exits"]
        for e in exits:
            if e["result"] == "closed":
                price = f"{e['price']:.2f}" if e["price"] is not None else "?"
                lines.append(f"{e['ticker']} sold @ {price} ({e['reason']})")
            else:
                lines.append(f"{e['ticker']} {e['result']} ({e['reason']})")
        await deps.notifier.send("\n".join(lines))
