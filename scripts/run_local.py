"""Run one of the Lambda runs locally against the account in .env (shared cTrader credentials
from SSM, as on Lambda). Data goes to data/local/store/ unless --store-dir says otherwise.

    uv run python scripts/run_local.py evening --env dev --dry-run
    uv run python scripts/run_local.py evening --env dev --at 2026-10-16T16:30 --dry-run

--dry-run prints order placements, cancels, take-profit amends and closes instead of sending
them. --at pretends the clock is at that New York time (keeping it running from there).
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path

import boto3

from btd.config import load_env
from btd.runs.app import (
    NY,
    RUNS,
    SHARED_PREFIX,
    PrintNotifier,
    SystemClock,
    load_secrets,
    run,
    ssm_parameters,
)
from btd.store import DirStore

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", choices=sorted(RUNS))
    ap.add_argument("--env", choices=["dev"], default="dev")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--at", type=datetime.fromisoformat, help="pretend New York time")
    ap.add_argument("--store-dir", type=Path, default=ROOT / "data" / "local" / "store")
    a = ap.parse_args()

    load_env(ROOT / ".env")
    own = {"ctrader-account-id": os.environ["CTRADER_ACCOUNT_ID"]}
    shared = ssm_parameters(boto3.client("ssm", region_name=os.environ["AWS_REGION"]),
                            SHARED_PREFIX)
    clock = SystemClock()
    if a.at:
        clock = SystemClock(a.at.replace(tzinfo=NY) - datetime.now(NY))
    asyncio.run(run(a.run, a.env, load_secrets(own, shared), store=DirStore(a.store_dir),
                    notifier=PrintNotifier(), clock=clock, dry_run=a.dry_run))


if __name__ == "__main__":
    main()
