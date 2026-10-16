"""Spike helper: a CTraderClient on the .env account, credentials from the shared SSM pair.

Refuses a live account. Outputs go to data/local/spike/ (gitignored)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import boto3

from btd.broker import DEMO_HOST, CTraderClient
from btd.config import load_env

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "local" / "spike"


def _shared() -> dict[str, str]:
    ssm = boto3.client("ssm", region_name=os.environ["AWS_REGION"])
    res = ssm.get_parameters_by_path(Path="/platform/shared", WithDecryption=True)
    return {p["Name"].rsplit("/", 1)[-1]: p["Value"] for p in res["Parameters"]}


@asynccontextmanager
async def demo_client() -> AsyncIterator[CTraderClient]:
    load_env(ROOT / ".env")
    s = _shared()
    client = CTraderClient(DEMO_HOST, client_id=s["ctrader-client-id"],
                           client_secret=s["ctrader-client-secret"],
                           access_token=s["ctrader-access-token"],
                           account_id=int(os.environ["CTRADER_ACCOUNT_ID"]))
    async with client:
        if await client.is_live():
            raise SystemExit("refusing: CTRADER_ACCOUNT_ID is a LIVE account")
        yield client
