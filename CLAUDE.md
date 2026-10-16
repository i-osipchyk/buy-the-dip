# Working in buy-the-dip

Forward test of the S&P 500 volatile-dip limit buy: an automated bot on a Pepperstone cTrader
**demo** account, running as AWS Lambdas, signals from yfinance daily bars.

This project follows the ~/dev platform conventions (see `../CLAUDE.md` and `../platform/docs/`),
with the deviations listed below.

Read these before writing code:

| File | What it is |
|---|---|
| `docs/STRATEGY_SPEC.md` | The strategy and backtest evidence. |
| `docs/ARCHITECTURE.md` | What we actually trade and how. **Wins over the spec** where they differ (its §3 lists every difference). |
| `docs/IMPLEMENTATION_PLAN.md` | Build order, phases and exit conditions. Work the current phase. |

## Rules that must not drift

- **The trading rules (ARCHITECTURE §2) are frozen.** Don't change a constant, a filter, the
  ranking, sizing or an exit without the user explicitly asking. Any rule change restarts the
  forward-test clock. If a rule looks wrong, say so; don't fix it. Spec §6 lists variants that
  were tested and rejected (stop losses, market entry, etc.); don't re-add them.
- **The core is pure.** `btd.core` takes bars, universe, ledger, positions, calendar and session
  and returns a `Plan`. No network, clock, env or AWS in it. The backtest calls the **same**
  `plan()` as the evening Lambda; never fork the logic between the two.
- **Indicators match Hermes exactly** (ARCHITECTURE §2.1): per-ticker rows, simple ATR5 (not
  Wilder), positive-price filter, ≥ 220 rows, fully adjusted yfinance bars. Hermes is not a
  dependency: nothing is imported from it.
- **Backtests use `sp500_history.csv`** (repo root) for point-in-time membership. It's the exact
  file Hermes used. It's gitignored and local only: never commit it, and keep it out of tests
  that run in CI.
- **The account is shared.** Identify our orders by `label="btd-<env>"` and
  `clientOrderId=btd-<env>-YYYYMMDD-<TICKER>-{E|X}`. Never read or touch anything else on the
  account. Equity is the virtual ledger (ARCHITECTURE §7), never the account balance, except once
  at genesis.
- **Runs are stateless and idempotent.** Derive everything from the broker, S3 snapshots and
  records each time. Retries come from the schedule; Lambda async retries stay at 0.
- **Record broker facts.** Fills, commission and swap in a record come from deal history, not
  from what the bot sent.
- **Anomalies alert; they are never auto-fixed.** An unexplained position, wrong volume or missing
  TP gets a Telegram alert and is left alone.
- **No automatic halt.** Drawdown −10% and −15% are alerts only (the user decided this).
- **All schedules are America/New_York** (EventBridge timezone); use `exchange_calendars` XNYS for
  sessions and holding-day counts. Never hard-code UTC offsets.

## Safety

- Never place, modify or close orders on a **live** account, or deploy `prod`, without an
  explicit instruction in the current conversation. Only `dev` (demo account) is deployed.
- Check which account `.env` points at before anything that trades; trading code refuses a live
  account in `dev`. Spike and smoke scripts refuse live accounts.
- The demo account also runs another strategy: never cancel, close or amend an order or position
  without our label, even in a script.
- Never print or commit secrets. SSM Parameter Store on Lambda (`/btd/<env>/*`, cTrader app and
  token in `/platform/shared/ctrader-*`, read only, never refreshed); an untracked `.env` locally.
- Tests are **offline**: fake broker, S3, Telegram and bar source, recorded fixtures, injected
  time. No test sleeps or hits the network (except `-m integration`).

## Deliberate deviations from the platform

- **Environments are `dev` and `prod`**, not the template's `demo`/`live` (as in gtb). A push to
  the `dev` branch deploys dev (Pepperstone **demo** account). **`prod` is not deployed**: it
  exists as config only, and has no deploy job and no AWS resources until the user decides to go
  live.
- **The cTrader client is copied from gtb** (`btd/broker/client.py`) and extended, not shared
  through the platform. This was the user's choice.
- App alerts and the daily summary go **straight to Telegram** through a project bot (gtb
  pattern). Infra alarms still go through `platform-alarms`.

## Commands

```bash
uv sync
uv run pytest                 # offline suite
uv run pytest -m integration  # real services
uv run ruff check .
uv run mypy
uv run python -m btd.backtest --help        # trades CSV in Hermes columns
uv run python scripts/run_local.py <evening|open_exit|morning_check|heartbeat> --env dev [--dry-run]
uv run python scripts/put_secrets.py --env dev   # .env -> SSM /btd/dev/*
```

Never run `terraform apply` locally. Deploys go through GitHub Actions only.
(The commands are created during Phases 0–3; if one doesn't exist yet, the plan says which phase
adds it.)

## Gates

Before calling anything done: `uv run pytest`, `uv run ruff check .` and `uv run mypy` pass (CI
runs all three). Changes to `btd.core` must keep the spec §4 reference-trade tests green.
