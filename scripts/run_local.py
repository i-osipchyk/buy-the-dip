"""Run one of the Lambda runs locally against the account in .env (shared cTrader credentials
from SSM, as on Lambda). Data goes to data/local/store/ unless --store-dir says otherwise.

    uv run python scripts/run_local.py evening --env dev --dry-run
    uv run python scripts/run_local.py evening --env dev --at 2026-10-16T16:30 --dry-run

--dry-run prints order placements, cancels, take-profit amends and closes instead of sending
them. --at pretends the clock is at that New York time (keeping it running from there).
--bucket writes to (and reads from) the env's S3 data bucket, the store the Lambdas use: a local
run then counts as that session's run. --telegram sends the messages instead of printing them.

    uv run python scripts/run_local.py evening --at 2026-10-15T16:30 \
        --bucket btd-dev-data-<account> --telegram
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path

import boto3

from btd.alerts import TelegramNotifier
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
from btd.runs.deps import Notifier
from btd.store import DirStore, S3Store, Store

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", choices=sorted(RUNS))
    ap.add_argument("--env", choices=["dev"], default="dev")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--at", type=datetime.fromisoformat, help="pretend New York time")
    ap.add_argument("--store-dir", type=Path, default=ROOT / "data" / "local" / "store")
    ap.add_argument("--bucket", help="use this S3 data bucket instead of --store-dir")
    ap.add_argument("--telegram", action="store_true", help="send messages to Telegram")
    a = ap.parse_args()
    if a.bucket and a.dry_run:
        ap.error("--dry-run with --bucket would record orders that were never sent")

    load_env(ROOT / ".env")
    own = {"ctrader-account-id": os.environ["CTRADER_ACCOUNT_ID"],
           "telegram-bot-token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
           "telegram-chat-id": os.environ.get("TELEGRAM_CHAT_ID", "")}
    shared = ssm_parameters(boto3.client("ssm", region_name=os.environ["AWS_REGION"]),
                            SHARED_PREFIX)
    clock = SystemClock()
    if a.at:
        clock = SystemClock(a.at.replace(tzinfo=NY) - datetime.now(NY))
    secrets = load_secrets(own, shared)
    store: Store = DirStore(a.store_dir)
    if a.bucket:
        store = S3Store(boto3.client("s3", region_name=os.environ["AWS_REGION"]), a.bucket)
    notifier: Notifier = PrintNotifier()
    if a.telegram:
        notifier = TelegramNotifier(secrets.telegram_bot_token, secrets.telegram_chat_id)
    asyncio.run(run(a.run, a.env, secrets, store=store, notifier=notifier, clock=clock,
                    dry_run=a.dry_run))


if __name__ == "__main__":
    main()
