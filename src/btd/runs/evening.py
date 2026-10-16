"""The evening run (ARCHITECTURE §5), scheduled every 30 min from 16:30 to 23:00 New York.
Idempotent: a session whose record is complete is not run again."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import pandas as pd

from .. import ledger
from ..alerts.messages import alert_text, evening_summary
from ..broker import CTraderError, PendingOrder, Position
from ..core import Holding, Plan, indicators, plan
from ..core.plan import MAX_HOLD
from ..data import universe as uni
from ..data.bars import Snapshot, validate
from ..data.tickers import from_venue
from .deps import Deps
from .guards import wrong_account

VOLUME_PER_SHARE = 100
PRICE_DIGITS = 2              # every US share on the venue (SPIKE §3)
WARN_DRAWDOWN, BREACH_DRAWDOWN = -0.10, -0.15      # alerts only, no halt (ARCHITECTURE §8)
DEADLINE = time(23, 0)        # New York: no valid bars by then -> degraded mode (ARCHITECTURE §8)


def key(env: str, kind: str, day: date, ext: str = "json") -> str:
    return f"{env}/{kind}/{day:%Y-%m-%d}.{ext}"


async def evening(deps: Deps) -> None:
    now = deps.clock.now()
    session = now.date()
    if not deps.calendar.is_session(session):
        return
    broker, env = deps.broker, deps.env
    record_key = key(env, "records", session)
    if (deps.store.get_json(record_key) or {}).get("complete"):
        return
    if await wrong_account(deps, session):
        return
    names = await broker.symbol_names()
    built = uni.build(deps.constituents.fetch(), names, _latest_universe(deps))
    universe = built.universe
    deps.store.put_json(key(env, "universe", session),
                        {"constituents": universe.constituents, "venue": universe.venue})
    deps.store.put_json(f"{env}/universe/latest.json",
                        {"constituents": universe.constituents, "venue": universe.venue})

    positions, pending = await broker.reconcile()
    mine = [p for p in positions if p.label == deps.label]
    my_orders = {o.client_order_id: o for o in pending if o.label == deps.label}
    ticker_of = {sid: from_venue(n) for n, sid in names.items()}
    held = {str(ticker_of[p.symbol_id]): p for p in mine}

    snapshot = deps.bars.fetch(sorted(set(universe.venue) | set(held)), session)
    problems = validate(snapshot, session, universe.venue, held)
    if problems:
        if now.time() >= DEADLINE:
            await _degraded(deps, session, now, problems, held, my_orders)
        return                                 # else: the next half-hourly attempt retries
    deps.store.put_bars(key(env, "bars", session, "parquet"), snapshot)

    genesis = await _genesis(deps, now)
    table = _day_table(snapshot, session, set(universe.venue))
    holdings = [Holding(t, p.volume / VOLUME_PER_SHARE, p.entry_price,
                        deps.calendar.held(p.opened_at.astimezone(now.tzinfo).date(), session))
                for t, p in held.items()]
    state_key = f"{env}/ledger/state.json"
    state = deps.store.get_json(state_key) or {}
    known = set(state.get("btd_positions", [])) | {p.position_id for p in mine}
    since = datetime.fromisoformat(genesis["at"])
    deals = await broker.deals(since, now) if since < now else []   # genesis made by this run
    mine_deals = [d for d in deals if d.position_id in known]
    book = ledger.compute(genesis["start_capital"], mine_deals, mine,
                          marks={p.position_id: float(table.close[t]) for t, p in held.items()},
                          btd_positions=known)
    peak = max(state.get("peak", genesis["start_capital"]), book.equity)
    drawdown = book.equity / peak - 1
    warned = bool(state.get("warned")) and drawdown <= WARN_DRAWDOWN
    alerts = list(built.alerts)
    if drawdown <= BREACH_DRAWDOWN:
        alerts.append(f"drawdown {drawdown:.1%} (equity {book.equity:,.0f} vs peak {peak:,.0f}): "
                      f"beyond the {BREACH_DRAWDOWN:.0%} review line")
    elif drawdown <= WARN_DRAWDOWN and not warned:
        alerts.append(f"drawdown {drawdown:.1%} (equity {book.equity:,.0f} vs peak {peak:,.0f}): "
                      f"past the {WARN_DRAWDOWN:.0%} warning")
        warned = True
    deps.store.put_json(state_key, {"btd_positions": sorted(known), "peak": peak,
                                    "warned": warned})
    day_start = datetime.combine(session, time(0), now.tzinfo)
    fills = [{"deal_id": d.deal_id, "position_id": d.position_id, "side": d.side,
              "price": d.price, "volume": d.volume, "time": d.time.isoformat(),
              "closing": d.closing, "commission": d.commission, "swap": d.swap,
              "gross_profit": d.gross_profit} for d in mine_deals if d.time >= day_start]
    decided = plan(table, holdings, book.equity)
    orders = await _execute(deps, decided, session, names, universe.venue, my_orders, alerts)
    positions_record = await _manage_positions(deps, decided, held, holdings)
    record = {
        "session": session.isoformat(), "env": env, "complete": True, "degraded": False,
        "at": now.isoformat(),
        "ledger": {"start_capital": genesis["start_capital"], "equity": book.equity,
                   "realized": book.realized, "unrealized": book.unrealized, "peak": peak,
                   "drawdown": drawdown},
        "candidates": [c.__dict__ for c in decided.candidates],
        "orders": orders,
        "fills": fills,
        "positions": positions_record,
        "alerts": alerts}
    deps.store.put_json(record_key, record)
    for text in alerts:
        await deps.notifier.send(alert_text(env, session, text))
    await deps.notifier.send(evening_summary(record))


def _latest_universe(deps: Deps) -> uni.Universe | None:
    doc = deps.store.get_json(f"{deps.env}/universe/latest.json")
    return uni.Universe(doc["constituents"], doc["venue"]) if doc else None


async def _genesis(deps: Deps, now: datetime) -> dict[str, Any]:
    k = f"{deps.env}/ledger/genesis.json"
    doc = deps.store.get_json(k)
    if doc is None:
        doc = {"start_capital": await deps.broker.balance(), "at": now.isoformat()}
        deps.store.put_json(k, doc)
    return doc


def _day_table(snapshot: Snapshot, session: date, members: set[str]) -> pd.DataFrame:
    rows = {}
    for ticker, bars in snapshot.items():
        d = indicators(bars)
        if d is None or session not in d.index:
            continue
        d["prev_high"] = d.high.shift(1)
        rows[ticker] = d.loc[session]
    table = pd.DataFrame(rows).T
    return table.assign(member=table.index.isin(members))


async def _execute(deps: Deps, decided: Plan, session: date, names: dict[str, int],
                   venue: dict[str, str], existing: dict[str, PendingOrder],
                   alerts: list[str]) -> list[dict[str, Any]]:
    nxt = deps.calendar.next_session(session)
    expiry = deps.calendar.close_at(nxt)
    specs = await deps.broker.symbol_specs([names[venue[e.ticker]] for e in decided.entries])
    wanted = {f"{deps.label}-{nxt:%Y%m%d}-{e.ticker}-E" for e in decided.entries}
    for cid, o in existing.items():
        if cid not in wanted:                           # an earlier session's or not planned
            await deps.broker.cancel_order(o.order_id)
    sent = []
    for e in decided.entries:
        sid = names[venue[e.ticker]]
        cid = f"{deps.label}-{nxt:%Y%m%d}-{e.ticker}-E"
        limit = round(e.limit, specs[sid].digits)
        volume = round(e.shares * VOLUME_PER_SHARE)
        order_id: int | None = None
        if cid in existing:                             # a retry: already at the broker
            order_id, status = existing[cid].order_id, "placed"
        else:
            try:
                order_id = await deps.broker.place_limit_order(
                    sid, "buy", volume=volume, limit_price=limit, expiry=expiry,
                    label=deps.label, client_order_id=cid)
                status = "placed"
            except CTraderError as err:                 # e.g. not enough margin: skip, no retry
                status = f"rejected: {err.code}"
                alerts.append(f"order {cid} {status}")
        order = {"client_order_id": cid, "ticker": e.ticker, "rank": e.rank, "limit": limit,
                 "shares": e.shares, "volume": volume, "order_id": order_id, "status": status}
        sent.append(order)
    return sent


async def _manage_positions(deps: Deps, decided: Plan, held: dict[str, Position],
                            holdings: list[Holding]) -> list[dict[str, Any]]:
    """Amend each staying position's take-profit to tonight's T (rounded to the venue's cents);
    flagged positions keep theirs until the open-exit run sells them."""
    out = []
    for h in holdings:
        p = held[h.ticker]
        target = decided.targets.get(h.ticker)
        if target is not None:
            target = round(target, PRICE_DIGITS)
            if p.take_profit != target:
                await deps.broker.amend_take_profit(p.position_id, target)
        out.append({"position_id": p.position_id, "ticker": h.ticker, "shares": h.shares,
                    "entry_price": p.entry_price, "opened_at": p.opened_at.isoformat(),
                    "held": h.held, "target": target, "exit": decided.exits.get(h.ticker)})
    return out


async def _degraded(deps: Deps, session: date, now: datetime, problems: list[str],
                    held: dict[str, Position], my_orders: dict[str, PendingOrder]) -> None:
    """No valid bars by the deadline: no entries, take-profits unchanged, time exits only."""
    for o in my_orders.values():
        await deps.broker.cancel_order(o.order_id)       # entry orders: none are planned tonight
    positions = []
    for ticker, p in held.items():
        n = deps.calendar.held(p.opened_at.astimezone(now.tzinfo).date(), session)
        positions.append({"position_id": p.position_id, "ticker": ticker,
                          "shares": p.volume / VOLUME_PER_SHARE, "entry_price": p.entry_price,
                          "opened_at": p.opened_at.isoformat(), "held": n, "target": None,
                          "exit": "time" if n >= MAX_HOLD else None})
    deps.store.put_json(key(deps.env, "records", session), {
        "session": session.isoformat(), "env": deps.env, "complete": True, "degraded": True,
        "at": now.isoformat(), "problems": problems, "ledger": None, "candidates": [],
        "orders": [], "fills": [], "positions": positions})
    await deps.notifier.send(alert_text(
        deps.env, session, f"no valid bars by {DEADLINE:%H:%M} ({'; '.join(problems)}). "
        "Degraded: no entries, take-profits unchanged, time exits only"))
