"""Spike item 3: how the shared DEMO account treats our order types. Run the stages in order:

    closed   while the market is closed (before 09:30 ET): mode, specs, a GTD buy limit far below
             the market (expires 16:00 ET today), a market buy (expected rejected or queued)
    open     after 09:35 ET: is the limit still pending; did the market buy fill (at what price);
             otherwise open the test position now
    evening  after 16:05 ET: did the limit expire at 16:00; amend the position's TP BELOW the last
             price while closed (gap-fill test); place a GTD limit while closed again
    next     after 09:35 ET the next session: did the TP fill at the open, at what price; then
             clean up
    status   print our orders/positions;   cleanup   cancel/close everything labelled btd-spike

Touches only orders and positions labelled ``btd-spike``, at the symbol's minimum volume. Refuses
a live account. Results are appended to data/local/spike/probe.jsonl.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from _conn import OUT, demo_client
from ctrader_open_api.messages import OpenApiMessages_pb2 as M
from ctrader_open_api.messages import OpenApiModelMessages_pb2 as MM

from btd.broker import CTraderClient, CTraderError

NY = ZoneInfo("America/New_York")
LABEL = "btd-spike"
SYMBOL = "AAPL.US"
SPEC_SAMPLE = ["AAPL.US", "BRK.B.US", "BF-B.US", "META.US", "NVR.US"]


def log(stage: str, **fields: Any) -> None:
    rec = {"stage": stage, "at": datetime.now(NY).isoformat(), **fields}
    print(json.dumps(rec, default=str, indent=1))
    with (OUT / "probe.jsonl").open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def close_16(day: date) -> datetime:
    return datetime.combine(day, time(16, 0), NY).astimezone(UTC)


async def ours(client: CTraderClient) -> tuple[list[Any], list[Any]]:
    positions, orders = await client.reconcile()
    return [p for p in positions if p.label == LABEL], [o for o in orders if o.label == LABEL]


async def last_bid(client: CTraderClient, symbol_id: int) -> float:
    end = datetime.now(UTC)
    bars = await client.trendbars(symbol_id, "H1", end - timedelta(days=5), end)
    return bars[-1].close


async def try_limit(client: CTraderClient, sid: int, vol: int, price: float, expiry: datetime,
                    tag: str) -> dict[str, Any]:
    cid = f"{LABEL}-{datetime.now(NY):%Y%m%d%H%M}-{tag}"
    try:
        oid = await client.place_limit_order(sid, "buy", volume=vol, limit_price=price,
                                             expiry=expiry, label=LABEL, client_order_id=cid)
        return {"accepted": True, "order_id": oid, "price": price, "expiry": expiry}
    except CTraderError as e:
        return {"accepted": False, "code": e.code, "description": e.description}


async def market_buy(client: CTraderClient, sid: int, vol: int) -> dict[str, Any]:
    try:
        res = await client._request(M.ProtoOANewOrderReq(
            ctidTraderAccountId=client.account_id, symbolId=sid, orderType=MM.MARKET,
            tradeSide=MM.BUY, volume=vol, label=LABEL,
            clientOrderId=f"{LABEL}-{datetime.now(NY):%Y%m%d%H%M}-MKT"))
        return {"accepted": True, "execution": MM.ProtoOAExecutionType.Name(res.executionType),
                "order_status": MM.ProtoOAOrderStatus.Name(res.order.orderStatus),
                "deal_price": res.deal.executionPrice if res.HasField("deal") else None}
    except CTraderError as e:
        return {"accepted": False, "code": e.code, "description": e.description}


async def stage(name: str) -> None:
    async with demo_client() as client:
        names = await client.symbol_names()
        sid = names[SYMBOL]
        spec = (await client.symbol_specs([sid]))[sid]
        vol = spec.min_volume
        today = datetime.now(NY).date()

        if name == "closed":
            specs = await client.symbol_specs([names[s] for s in SPEC_SAMPLE if s in names])
            bid = await last_bid(client, sid)
            limit = round(bid * 0.8, 2)
            log(name, account_mode=await client.account_mode(),
                specs={s: asdict(specs[names[s]]) for s in SPEC_SAMPLE if s in names},
                last_bid=bid,
                gtd_limit_while_closed=await try_limit(client, sid, vol, limit, close_16(today),
                                                       "E"),
                market_buy_while_closed=await market_buy(client, sid, vol))
        elif name == "open":
            positions, orders = await ours(client)
            if not positions:
                log(name, note="no position from the queued market buy: opening one now",
                    market_buy=await market_buy(client, sid, vol))
                positions, orders = await ours(client)
            deals = await client.deals(datetime.now(UTC) - timedelta(hours=8), datetime.now(UTC))
            log(name, positions=positions, orders=orders,
                deals=[d for d in deals if d.position_id in {p.position_id for p in positions}])
        elif name == "evening":
            positions, orders = await ours(client)
            bid = await last_bid(client, sid)
            amend: dict[str, Any] = {}
            if positions:
                tp = round(bid * 0.995, 2)              # below the market: fills at the open
                try:
                    await client.amend_take_profit(positions[0].position_id, tp)
                    amend = {"accepted": True, "tp": tp, "below_last_bid": bid}
                except CTraderError as e:
                    amend = {"accepted": False, "tp": tp, "code": e.code,
                             "description": e.description}
            nxt = today + timedelta(days=3 if today.weekday() == 4 else 1)
            log(name, positions_before=positions, orders_after_16=orders, last_bid=bid,
                tp_below_market_while_closed=amend,
                gtd_limit_while_closed_evening=await try_limit(
                    client, sid, vol, round(bid * 0.8, 2), close_16(nxt), "E2"),
                after=await ours(client))
        elif name == "next":
            positions, orders = await ours(client)
            deals = await client.deals(datetime.now(UTC) - timedelta(days=4), datetime.now(UTC))
            log(name, positions=positions, orders=orders,
                deals=[d for d in deals if d.closing])
        elif name == "status":
            log(name, ours=await ours(client))
        elif name == "cleanup":
            positions, orders = await ours(client)
            for o in orders:
                await client.cancel_order(o.order_id)
            for p in positions:
                await client.close_position(p.position_id, volume=p.volume)
            log(name, cancelled=[o.order_id for o in orders],
                closed=[p.position_id for p in positions])
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    asyncio.run(stage(sys.argv[1] if len(sys.argv) > 1 else ""))
