"""Wiring: real clock, cTrader client, store, notifier and sources around the runs, for the Lambda
entry points and ``scripts/run_local.py``. Any run error is alerted, then re-raised (so the
Lambda error alarm fires too). Secrets are read from SSM on every invocation: after the platform
refreshes the shared cTrader pair, the old access token is dead (platform conventions § Secrets).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..alerts import TelegramNotifier
from ..alerts.messages import alert_text
from ..broker import DEMO_HOST, LIVE_HOST, CTraderClient
from ..calendar import Calendar
from ..data.sources import WikipediaConstituents, YFinanceSource
from ..store import Store
from .deps import Broker, Deps, Notifier
from .evening import evening
from .heartbeat import heartbeat
from .morning_check import morning_check
from .open_exit import open_exit

NY = ZoneInfo("America/New_York")
HOST = {"dev": DEMO_HOST, "prod": LIVE_HOST}
SHARED_PREFIX = "/platform/shared/"
RUNS: Mapping[str, Callable[[Deps], Awaitable[None]]] = {
    "evening": evening, "open_exit": open_exit, "morning_check": morning_check,
    "heartbeat": heartbeat}


class SystemClock:
    """Wall-clock New York time, optionally shifted (local runs pretending to be at 16:30)."""

    def __init__(self, offset: timedelta = timedelta(0)) -> None:
        self.offset = offset

    def now(self) -> datetime:
        return datetime.now(NY) + self.offset


class PrintNotifier:
    async def send(self, text: str) -> None:
        print(f"--- message ---\n{text}\n---------------")


class DryRunBroker:
    """Reads go to the real client; writes (place, cancel, amend, close) are printed instead."""

    def __init__(self, client: CTraderClient) -> None:
        self._client = client
        self._ids = iter(range(-1, -1_000_000, -1))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    async def place_limit_order(self, symbol_id: int, side: str, **kw: Any) -> int:
        print(f"DRY RUN place_limit_order({symbol_id}, {side}, {kw})")
        return next(self._ids)

    async def cancel_order(self, order_id: int) -> None:
        print(f"DRY RUN cancel_order({order_id})")

    async def amend_take_profit(self, position_id: int, take_profit: float) -> None:
        print(f"DRY RUN amend_take_profit({position_id}, {take_profit})")

    async def close_position(self, position_id: int, *, volume: int) -> None:
        print(f"DRY RUN close_position({position_id}, volume={volume})")


@dataclass(frozen=True)
class Secrets:
    client_id: str
    client_secret: str = field(repr=False)
    access_token: str = field(repr=False)
    account_id: int
    telegram_bot_token: str = field(repr=False, default="")
    telegram_chat_id: str = ""


def ssm_parameters(client: Any, prefix: str) -> dict[str, str]:
    """Every parameter directly under ``prefix``, decrypted, keyed by its last path segment."""
    out: dict[str, str] = {}
    kwargs: dict[str, Any] = {"Path": prefix, "WithDecryption": True, "Recursive": False}
    while True:
        res = client.get_parameters_by_path(**kwargs)
        for p in res["Parameters"]:
            out[p["Name"].rsplit("/", 1)[-1]] = p["Value"]
        if not res.get("NextToken"):
            return out
        kwargs["NextToken"] = res["NextToken"]


def load_secrets(own: Mapping[str, str], shared: Mapping[str, str]) -> Secrets:
    """``own``: ``/btd/<env>/`` (or .env names locally); ``shared``: ``/platform/shared/``."""
    return Secrets(
        client_id=shared["ctrader-client-id"], client_secret=shared["ctrader-client-secret"],
        access_token=shared["ctrader-access-token"],
        account_id=int(own["ctrader-account-id"]),
        telegram_bot_token=own.get("telegram-bot-token", ""),
        telegram_chat_id=own.get("telegram-chat-id", ""))


async def run(name: str, env: str, secrets: Secrets, *, store: Store, notifier: Notifier,
              clock: SystemClock | None = None, dry_run: bool = False) -> None:
    clock = clock or SystemClock()
    try:
        async with CTraderClient(HOST[env], client_id=secrets.client_id,
                                 client_secret=secrets.client_secret,
                                 access_token=secrets.access_token,
                                 account_id=secrets.account_id) as client:
            broker: Broker = DryRunBroker(client) if dry_run else client
            deps = Deps(env=env, broker=broker, store=store, notifier=notifier, clock=clock,
                        bars=YFinanceSource(), constituents=WikipediaConstituents(),
                        calendar=Calendar())
            await RUNS[name](deps)
    except Exception as e:
        await notifier.send(alert_text(env, clock.now().date(),
                                       f"{name} run failed: {type(e).__name__}: {e}"))
        raise


# --- Lambda entry points (one image; each function names its handler) ----------------------

def _lambda(name: str) -> None:
    import boto3

    from ..store import S3Store

    env = os.environ["ENV"]
    ssm = boto3.client("ssm")
    secrets = load_secrets(ssm_parameters(ssm, f"/btd/{env}/"),
                           ssm_parameters(ssm, SHARED_PREFIX))
    store = S3Store(boto3.client("s3"), os.environ["DATA_BUCKET"])
    notifier = TelegramNotifier(secrets.telegram_bot_token, secrets.telegram_chat_id)
    asyncio.run(run(name, env, secrets, store=store, notifier=notifier))


def evening_handler(event: object, context: object) -> None:
    _lambda("evening")


def open_exit_handler(event: object, context: object) -> None:
    _lambda("open_exit")


def morning_check_handler(event: object, context: object) -> None:
    _lambda("morning_check")


def heartbeat_handler(event: object, context: object) -> None:
    _lambda("heartbeat")
