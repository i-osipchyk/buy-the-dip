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
  - [ ] account mode: hedging or netting;
  - [ ] a GTD buy limit **placed while the market is closed** is accepted (**go/no-go**);
  - [ ] a position TP amend while closed;
  - [ ] a TP gap fill at the open price;
  - [ ] GTD expiry at 16:00 ET;
  - [ ] `minVolume` / `stepVolume` on a sample, including `BRK.B.US`.
- [ ] **4. Pepperstone D1 against yfinance:** bar boundaries and the close difference
      distribution, which sets the §4.1 threshold.
- [ ] **5. The Wikipedia scrape** ∩ venue symbols = about 478, with every mapping resolved.

**Exit:** every item is answered in `docs/SPIKE.md`. If item 3's closed-market placement fails, or
item 1 is unreliable, **stop and revisit the design with the user** before Phase 2.

---

## Phase 2: Pure core and backtest (TDD, offline)

- [ ] `core/indicators.py`: ARCHITECTURE §2.1 exactly (row-based, positive-price filter, ≥ 220
      rows, NY-normalized dates).
- [ ] `core/signals.py`: candidates, the held/flagged rule, ranking with a ticker tie-break, and
      `free` including flagged exits.
- [ ] `core/sizing.py`: alloc, gross cap with the lowest rank trimmed first, round down to step,
      min-size skips.
- [ ] `core/exits.py`: the target `T`, rebound, time (XNYS session count) and removal flags.
- [ ] `core/plan.py`: `plan(...) -> Plan` (entries, TPs, flags, the candidate table with skip
      reasons).
- [ ] Tests: the spec §4 reference trades (META, EXPE, GLW, CF) to the cent; unit tests for slot
      freeing, the gross cap, rounding, tie-breaks, `T` below entry, and a time exit at exactly
      10.
- [ ] `backtest/`: a fill simulator around `plan()` (touch fill at `min(open, L)`, target at
      `max(open, T)`, next-open exits at `Open`, removal). CLI arguments: window, cost bp,
      membership CSV (default `sp500_history.csv` at the repo root, the file Hermes used;
      gitignored, latest snapshot ≤ date), optional venue list, bars directory. It writes
      `trades_<tag>.csv` in Hermes's columns and an equity CSV.
- [ ] A yfinance bar downloader for the backtest (cached locally, gitignored).

**Exit:** the reference trades pass, and **the user's comparison of btd's trades CSV with Hermes
on the same bars is accepted.** Rules frozen from here.

---

## Phase 3: Plumbing (offline against fakes)

- [ ] `data/tickers.py`: canonical ↔ yfinance ↔ cTrader mapping and tests.
- [ ] `data/bars.py`: `BarSource`, `YFinanceSource`, validation (§4.1), snapshot to S3, the cTrader
      D1 cross-check.
- [ ] `data/universe.py`: the Wikipedia scrape, sanity guards, venue intersection, snapshot.
- [ ] `broker/client.py`: copy from gtb; add limit + GTD, amend SL/TP, symbols list with volume
      specs, close position, deals with commission and swap. A fake broker for tests.
- [ ] `ledger.py`: genesis (write-once), recompute from labeled deals, peak and drawdown.
- [ ] `records/`: the session record model and S3 store; `scripts/trades_from_records.py`.
- [ ] `runs/evening.py`: an idempotent state machine (no-op if complete, fetch → reconcile → ledger
      → plan → execute → record → summary), degraded mode at 23:00, the passive finality diff.
- [ ] `runs/open_exit.py`, `runs/morning_check.py`, `runs/heartbeat.py`, and `runs/app.py`
      handlers.
- [ ] `alerts/`: Telegram notifier and messages (from gtb); summary, alerts, drawdown alerts at
      −10% and −15% (repeated).
- [ ] Execute/reconcile tests: a double run is a no-op, a retry finds existing orders by
      `clientOrderId`, foreign-label orders are untouched, anomalies alert.

**Exit:** the full offline suite passes. A local `scripts/run_local.py evening --env dev` against
the demo account produces a correct plan, with order placement behind a `--dry-run` flag.

---

## Phase 4: dev on demo

- [ ] Infra: `data-bucket`, `lambda-app` with the four functions and §5 schedules (timezone
      America/New_York), `schedules_enabled = false` at first.
- [ ] Wire the repo in platform bootstrap (the user applies it) and the GitHub `dev` environment;
      put the SSM secrets.
- [ ] Deploy dev. **One supervised evening run** with the user watching: plan reviewed, orders
      checked on the account, then the 09:35 / 09:50 runs the next morning.
- [ ] Enable the schedules. **The forward-test clock starts at the first unsupervised session;**
      the ledger genesis is captured then.

**Exit:** five consecutive sessions with complete records, no anomalies, and summaries received.

---

## Phase 5: Monthly parity (by the first month-end)

- [ ] `scripts/parity.py`: the btd backtest over the forward period on the stored snapshots,
      against the derived live `trades.csv`. It reports signal and order match %, fill rate,
      slippage (entry against `L`, target against `T`, open-exit against `Open`), and the mean
      trade after costs.
- [ ] A finality-diff review after the first month (keep 16:30 or move it later).

**Exit:** the first monthly report is produced and reviewed with the user.
