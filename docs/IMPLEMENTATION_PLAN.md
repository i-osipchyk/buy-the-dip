# Implementation plan

Build order for the forward test described in [`ARCHITECTURE.md`](ARCHITECTURE.md). Each phase
ends with a checkable exit condition. Don't start a phase until the previous one has exited,
except where marked as parallel.

---

## Phase 0: Scaffolding

- [x] `uvx copier copy --trust ~/dev/platform .` into this repo: `project_name=buy-the-dip`,
      `slug=btd`, `package=btd`, `uses_llm=no`, `deploy_lambda=yes`. Keep the existing
      `CLAUDE.md` and `docs/`; merge the template's `CLAUDE.md` lines into ours.
- [x] Switch the environments to `dev`/`prod` (as gtb does): `infra/env/dev.tfvars` only and a
      deploy workflow for `dev` (push to the `dev` branch). **No prod job.**
- [x] Runtime deps: `ctrader-open-api`, `protobuf`, `boto3`, `httpx`, `pandas`, `pyarrow`,
      `yfinance`, `exchange_calendars`, `lxml` (or `beautifulsoup4`) for the Wikipedia scrape.
- [x] Empty package skeleton matching ARCHITECTURE §12.1.

**Exit:** `uv run pytest`, `uv run ruff check .` and `uv run mypy` pass on the skeleton; CI is green.

*Done 2026-10-16 locally* (template v0.1.2; pytest, ruff and mypy pass). CI is green once the repo
is pushed (not done yet; the user pushes). Infra still has the template's `example` function;
Phase 4 replaces it with the real functions and schedules.

---

## Phase 1: Spike (throwaway, about one week)

Scripts in `scripts/spike/`, plus one minimal Lambda for item 1. Record the answers in
`docs/SPIKE.md`.

- [ ] **1. yfinance from Lambda (eu-west-1):** 478 tickers × 300 days, `auto_adjust=True`, at
      16:30 and 17:00 ET for 5 sessions. Success rate, latency, missing names.
- [ ] **2. Close finality:** the 16:30 close against the 20:00 close against the next-day close,
      per name.
- [ ] **3. cTrader on the shared demo account** (`scripts/spike/broker_probe.py`, demo only,
      refuses a live account):
  - [x] account mode: hedging or netting;
  - [x] a GTD buy limit **placed while the market is closed** is accepted (**go/no-go**);
  - [ ] a position TP amend while closed;
  - [ ] a TP gap fill at the open price;
  - [ ] GTD expiry at 16:00 ET;
  - [x] `minVolume` / `stepVolume` on a sample, including `BRK.B.US`.
- [x] **4. Pepperstone D1 against yfinance:** bar boundaries and the close difference
      distribution, which sets the §4.1 threshold.
- [x] **5. The Wikipedia scrape** ∩ venue symbols = about 478, with every mapping resolved.

**Exit:** every item is answered in `docs/SPIKE.md`. If item 3's closed-market placement fails, or
item 1 is unreliable, **stop and revisit the design with the user** before Phase 2.

---

## Phase 2: Pure core and backtest (TDD, offline)

- [x] `core/indicators.py`: ARCHITECTURE §2.1 exactly (row-based, positive-price filter, ≥ 220
      rows, NY-normalized dates).
- [x] `core/signals.py`: candidates, the held/flagged rule, ranking with a ticker tie-break, and
      `free` including flagged exits.
- [x] `core/sizing.py`: alloc, gross cap with the lowest rank trimmed first, round down to step,
      min-size skips.
- [x] `core/exits.py`: the target `T`, rebound, time (XNYS session count) and removal flags.
- [x] `core/plan.py`: `plan(...) -> Plan` (entries, TPs, flags, the candidate table with skip
      reasons).
- [x] Tests: the spec §4 reference trades (META, EXPE, GLW, CF) to the cent; unit tests for slot
      freeing, the gross cap, rounding, tie-breaks, `T` below entry, and a time exit at exactly
      10.
- [x] `backtest/`: a fill simulator around `plan()` (touch fill at `min(open, L)`, target at
      `max(open, T)`, next-open exits at `Open`, removal). CLI arguments: window, cost bp,
      membership CSV (default `sp500_history.csv` at the repo root, the file Hermes used;
      gitignored, latest snapshot ≤ date), optional venue list, bars directory. It writes
      `trades_<tag>.csv` in Hermes's columns and an equity CSV.
- [ ] A yfinance bar downloader for the backtest (cached locally, gitignored). *Not needed
      yet: the backtest reads Hermes's cache, which is the same format.*

**Exit:** the reference trades pass, and **the user's comparison of btd's trades CSV with Hermes
on the same bars is accepted.** Rules frozen from here.

*Code done 2026-10-16* (67 tests). Pre-check against Hermes's saved runs on the same bar cache
(`hermes/.hermes_cache/bars/yfinance`, `sp500_history.csv`, 5 bp):
- holdout 2023–: `trades_ho_A_fix.csv` 451 trades, **all 451 identical** (dates, reasons, prices);
- IS 2011–22: `trades_is_A_fix.csv` 991 trades, **all 991 identical**; btd has one more (FSLR
  2022-12-28): Hermes drops a position flagged for the next open on the window's last day;
  btd closes it as `end`;
- the older `trades_is_d0.9_s10_c5_limit.csv` predates Hermes's panel fix, so don't compare
  with it;
- Pepperstone-only holdout (Hermes's 478-name list, 3 bp): 428 trades, +0.990%, against the spec's
  444 / +0.98%. That Hermes run isn't saved and its venue filter isn't known, so the user compares it.
Awaiting the user's comparison.

---

## Phase 3: Plumbing (offline against fakes)

- [x] `data/tickers.py`: canonical ↔ yfinance ↔ cTrader mapping and tests.
- [x] `data/bars.py`: `BarSource`, `YFinanceSource`, validation (§4.1), snapshot to S3, the cTrader
      D1 cross-check.
- [x] `data/universe.py`: the Wikipedia scrape, sanity guards, venue intersection, snapshot.
- [x] `broker/client.py`: copy from gtb; add limit + GTD, amend SL/TP, symbols list with volume
      specs, close position, deals with commission and swap. A fake broker for tests.
- [x] `ledger.py`: genesis (write-once), recompute from labeled deals, peak and drawdown.
- [x] `records/`: the session record model and S3 store; `scripts/trades_from_records.py`.
- [x] `runs/evening.py`: an idempotent state machine (no-op if complete, fetch → reconcile → ledger
      → plan → execute → record → summary), degraded mode at 23:00, the passive finality diff.
- [x] `runs/open_exit.py`, `runs/morning_check.py`, `runs/heartbeat.py`, and `runs/app.py`
      handlers.
- [x] `alerts/`: Telegram notifier and messages (from gtb); summary, alerts, drawdown alerts at
      −10% and −15% (repeated).
- [x] Execute/reconcile tests: a double run is a no-op, a retry finds existing orders by
      `clientOrderId`, foreign-label orders are untouched, anomalies alert.

**Exit:** the full offline suite passes. A local `scripts/run_local.py evening --env dev` against
the demo account produces a correct plan, with order placement behind a `--dry-run` flag.

---

*Done 2026-10-16* (109 tests). Local dry run `run_local.py evening --at 2026-10-15T16:30
--dry-run` against the demo account, live Yahoo and Wikipedia: 15 s, 10 signals → 10 orders
(a hardware-tech selloff), prices in cents, GTD 16:00 ET 10-16. Found and fixed on the way: the
deal list rejects an empty window (`INCORRECT_BOUNDARIES`) on the run that creates the genesis.
A 120-day window is fine, so there's no chunking.

**Not wired yet (functions exist where noted):**
- [ ] the cTrader D1 close cross-check in the evening (`data.bars.cross_check` is tested).
      478 trendbar requests a night is slow, so the plan is to cross-check only tonight's
      candidates and held names;
- [ ] the passive 20:00 finality diff;
- [ ] `S3Store` is only exercised on Lambda (tests use `DirStore` through the same interface).

## Phase 4: dev on demo

- [x] Infra: the four functions (`evening` 600 s / 2 GB, `open_exit`, `morning_check`,
      `heartbeat`) and the §5 schedules (America/New_York), gated by `trading_enabled` (false),
      log retention 400 days. `tests/test_infra.py` keeps `main.tf` in line with the handlers
      and the §5 times. `spike_fetch` stays until Phase 1 closes.
- [x] Repo wired in platform bootstrap, GitHub `dev` environment, SSM secrets (done in Phase 1).
- [ ] Deploy dev (push `dev`).
- [ ] **One supervised evening run** with the user watching, after 16:30 ET on a session:
      `aws lambda invoke --function-name btd-dev-evening out.json`, then the Telegram summary,
      `aws logs tail /aws/lambda/btd-dev-evening --since 15m`, and the `btd-dev` orders on the
      account. The next morning: `btd-dev-open_exit` (≥ 09:35 ET) and `btd-dev-morning_check`
      (≥ 09:50 ET) by hand.
      This first run **captures the ledger genesis** (the account balance) and places real demo
      orders, so the supervised session is session 1 of the forward test.
- [ ] Flip `trading_enabled = true` in `infra/env/dev.tfvars` and push.

**Exit:** five consecutive sessions with complete records, no anomalies, and summaries received.

---

## Phase 5: Monthly parity (by the first month-end)

- [ ] `scripts/parity.py`: the btd backtest over the forward period on the stored snapshots,
      against the derived live `trades.csv`. It reports signal and order match %, fill rate,
      slippage (entry against `L`, target against `T`, open-exit against `Open`), and the mean
      trade after costs.
- [ ] A finality-diff review after the first month (keep 16:30 or move it later).

**Exit:** the first monthly report is produced and reviewed with the user.
