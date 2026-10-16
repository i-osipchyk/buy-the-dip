"""The morning check (ARCHITECTURE §5, 09:50 New York): the broker matches last evening's
record. Alerts only; it never fixes anything (ARCHITECTURE §6.3)."""

from __future__ import annotations

from datetime import datetime, time

from ..alerts.messages import alert_text
from .deps import Deps
from .evening import key


async def morning_check(deps: Deps) -> None:
    session = deps.clock.now().date()
    if not deps.calendar.is_session(session):
        return
    record = deps.store.get_json(key(deps.env, "records", deps.calendar.previous_session(session)))
    positions, pending = await deps.broker.reconcile()
    now = deps.clock.now()
    deals = await deps.broker.deals(datetime.combine(session, time(0), now.tzinfo), now)
    filled = {d.order_id for d in deals}
    orders = {o.order_id: o for o in pending if o.label == deps.label}
    expiry = deps.calendar.close_at(session)
    open_ = {p.position_id: p for p in positions if p.label == deps.label}
    problems = []
    for r in (record or {}).get("positions", []):
        if r["exit"] and r["position_id"] in open_:
            problems.append(f"{r['ticker']} (position {r['position_id']}) should have been sold "
                            f"at the open ({r['exit']}) but is still open")
        p = open_.get(r["position_id"])
        if not r["exit"] and p is not None and p.take_profit != r["target"]:
            problems.append(f"{r['ticker']} (position {r['position_id']}) has take-profit "
                            f"{p.take_profit}, expected {r['target']}")
    for o in (record or {}).get("orders", []):
        if o["status"] != "placed" or o["order_id"] in filled:
            continue
        cid, oid = o["client_order_id"], o["order_id"]
        live = orders.get(oid)
        if live is None:
            problems.append(f"entry order {cid} ({oid}) is neither pending nor filled")
        elif live.expiry != expiry:
            got = live.expiry.astimezone(expiry.tzinfo) if live.expiry else None
            problems.append(f"entry order {cid} ({oid}) expires {got}, expected {expiry}")
    for text in problems:
        await deps.notifier.send(alert_text(deps.env, session, text))
