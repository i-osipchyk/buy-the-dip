# Architecture: S&P 500 volatile-dip forward test

How the forward test of the strategy in [`STRATEGY_SPEC.md`](STRATEGY_SPEC.md) is run. The spec
says *what the strategy is and what the backtest showed*. This document says *what we actually
trade, how, and how we judge it*. Where the two differ, this document wins for the forward test,
and every difference is listed in [§3](#3-differences-from-the-spec).

Decisions agreed on 2026-10-16 (grilling session). The decision log is in [§14](#14-decision-log).

---

## 1. Goal and phases

Find out (a) whether the edge holds on unseen data and (b) whether it survives real execution
(limit fill rate, slippage, CFD costs).

| Phase | What | Exit |
|---|---|---|
| Spike | Prove the assumptions the design rests on ([§13](#13-open-questions-spike)) | every spike item answered; evening pending orders accepted |
| Build | Pure core + in-repo backtest; plumbing | the user's comparison of btd's backtest trades with Hermes passes |
| Forward test | `dev` env on the shared Pepperstone **demo** account, automated | ~100 trades, then the spec §5.1 verdict |
| Live | `prod` env pointed at a live account | separate decision after the verdict; **not deployed now** |

**The rules are frozen** from the first unsupervised session until the verdict. Any change to a
trading rule restarts the forward-test clock. Plumbing and infra fixes don't.

---

## 2. Trading rules (as implemented)

The rules are the spec's §2, unchanged. This section pins down the details the spec leaves open,
taken from the Hermes backtest code (`hermes/research/dip_buy/dip_study.py`), which the in-repo
backtest must reproduce trade for trade.

### 2.1 Indicators

Per ticker, over **that ticker's own rows** (not calendar days), on fully adjusted
(`auto_adjust=True`) yfinance daily bars:

1. Index the bars by date: yfinance timestamp → America/New_York → normalized date; keep the
   last row of duplicate dates.
2. Drop any row where open, high, low or close is ≤ 0.
3. Exclude the ticker entirely if fewer than **220** rows remain.
4. `prev_close = close.shift(1)` (previous **row**).
   `TR = max(high − low, |high − prev_close|, |low − prev_close|)`.
   `ATR5 = TR.rolling(5).mean()` (simple, not Wilder). `SMA200 = close.rolling(200).mean()`.
   `DayRet = close / prev_close − 1`. `VolPct = 100 · ATR5 / close`.

### 2.2 Signal and ranking (after the close of day t)

`candidate = member[t] ∧ close > SMA200 ∧ DayRet < −0.03 ∧ VolPct > 3 ∧ not held`.

- **Held** means a btd position that is open and **not** flagged to exit at the next open. The
  backtest processes next-open exits before entries, so a position leaving at the open does not
  block its own ticker. The account is hedged (spike), so such a re-entry is a separate position. (A rebound-flagged name can't signal anyway: `C[t] > H[t−1]` implies an up
  day.)
- Rank by `VolPct` descending; ties by ticker ascending, for determinism.
- `free = 10 − open + flagged_for_open_exit`. Order the top `free` candidates. Do **not**
  over-order. A candidate that turns out to have no bar the next day just doesn't fill. Its slot
  is not passed down the list.

### 2.3 Sizing

- `btd_equity[t]` from the ledger ([§7](#7-ledger)), marked at the day-t close.
- `alloc = 0.10 · btd_equity[t]`.
- **Gross cap across tonight's orders:** `Σ held notional at Close[t] (excluding flagged exits)
  + Σ alloc of tonight's orders ≤ btd_equity[t]`. If it binds, trim the **lowest-ranked** order
  first, then drop it.
- `volume = floor_to_step(alloc / L)`: sized at the limit price, rounded **down** to the symbol's
  `stepVolume`.
- Skip the order if `volume < minVolume` or if `volume · L < 0.2 · (0.10 · btd_equity[t])`. Record
  why.

### 2.4 Entry (session t+1)

Buy limit at `L = Close[t] − 0.9 · ATR5[t]`, GTD-expiring at 16:00 ET on t+1. Placed in the
evening of t. A gap below `L` fills at the open (limit or better).

### 2.5 Exits

Let e be the entry session and `held = trading days since e` (`held = 0` on e). Order of
evaluation, as in the backtest:

1. **Target**, intraday from e+1. It's the position's take-profit at `T[d] = Close[d−1] + 0.5 ·
   ATR5[d−1]`, amended every evening (first set on the evening of e). A gap above `T` fills at the
   open. `T` may be below the entry price, and that's intended.
2. **Rebound**, at the close of d ≥ e: `Close[d] > High[d−1]` → flag to exit at the next open.
3. **Time**, at the close of d: `held ≥ 10` → flag.
4. **Index removal**: the ticker isn't in the day's universe snapshot → flag.

If the target filled on d, the evening rules are skipped. A flagged position keeps its TP
overnight: a gap above `T` fills the TP at the open, which is the same outcome. Flagged exits are
sent as market closes by the **open-exit** run at 09:35 ET ([§5](#5-runs-and-schedule)). There is
no stop loss.

---

## 3. Differences from the spec

| # | Spec | Forward test | Why |
|---|---|---|---|
| 1 | Rebound, time and removal exits sell **at the next open** | Market close at **09:35 ET** (open-exit run) | cTrader has no market-on-open order, and market orders are rejected while closed. Measured as slippage against `Open[d+1]`. These are about 10% of exits. |
| 2 | Removal exit "at that day's close (or next open)"; the backtest uses the close | Next session, 09:35 ET, after the daily universe snapshot shows the removal | Detection lags the effective date by up to a day. |
| 3 | Size = 10% of equity / fill price (backtest) | 10% of equity / `L`, rounded down to step; conservative gross cap across all of tonight's orders | Volume is fixed at order time. A gap fill is slightly under 10% notional. |
| 4 | "Account equity" | Virtual **btd ledger** on a shared account ([§7](#7-ledger)) | The demo account also runs another strategy. |
| 5 | Orders placed before 09:30 | Placed the **evening** before (16:30–23:00 ET) | Same session effect; no morning dependency for entries and targets. |
| 6 | Drawdown > 15% → stop and review | **Alarm only** (−10% warning, −15% breach, repeated daily). No automatic halt. | The review is a human decision. |
| 7 | — | **Degraded mode** on a night with no valid data ([§8](#8-failure-handling)) | Data can fail. |

The universe is current constituents ∩ venue, as in the spec. The Hermes backtest used
point-in-time membership. That's the same rule, applied to today.

---

## 4. Data

### 4.1 Bars: yfinance

- One source for signals: **yfinance, `auto_adjust=True`** (splits and dividends), the same data
  as the backtest.
- **Every night, re-download about 300 trading days** for the whole universe (batched
  `yf.download`). There's no incremental store: each dividend re-bases the adjusted history, so
  appending a new bar to old bars would mix bases. The latest bar's adjustment factor is 1, so
  `Close[t]`, `L` and `T` are real tradable prices.
- Behind a `BarSource` interface that writes an immutable snapshot `dev/bars/<date>.parquet`. If
  Yahoo blocks Lambda, a home fetcher or a paid vendor replaces only this stage.
- **Validation before planning:** the last bar is dated t; ≥ 98% of the universe has a bar for t;
  no NaN in OHLC for t; every held ticker has a bar for t.
- **Cross-check:** `Close[t]` against the cTrader D1 close per symbol. A D1 bar opens at 17:00
  New York the evening **before** its session (session date = `(open in NY + 7 h).date()`). Log
  names differing by more than 150 bp; alert if more than 5% of names exceed it (the spike's worst
  normal-day difference was 112 bp; [SPIKE §4](SPIKE.md#4-pepperstone-d1-against-yfinance)).
- **Finality check (passive):** a 20:00 ET re-fetch diffs `Close[t]`, signals, `L` and `T`
  against what was traded and logs the result. It never changes orders. Review after a month.

### 4.2 Universe

- **Constituents:** a daily scrape of Wikipedia's "List of S&P 500 companies". Sanity: 495–510
  names, and at most 5 changes against the previous snapshot. Otherwise **alert and keep the
  previous snapshot**.
- **Venue:** `ProtoOASymbolsListReq`, keep `<TICKER>.US`, ignore the `-24` and `_SB*` variants.
  Store symbol id, `minVolume`, `stepVolume`.
- **Universe = constituents ∩ venue** (about 478). The snapshot is `dev/universe/<date>.json`,
  including the venue specs.
- **Canonical ticker:** S&P dot style (`BRK.B`). yfinance: dots become dashes (`BRK-B`). The
  venue spells share classes **inconsistently** (`BRK.B.US` but `BF-B.US`), so the canonical →
  venue name map is built from the venue list (`from_venue`), never by rule.
- A ticker change (FB → META) shows as remove + add: it trips the sanity alert, and you decide.

### 4.3 Calendar

`exchange_calendars` (XNYS): sessions, holidays, early closes. Runs exit quietly on non-sessions.
`held` and "next session" are counted in XNYS sessions.

---

## 5. Runs and schedule

All schedules are EventBridge Scheduler with `timezone = "America/New_York"`, MON–FRI, via the
platform `lambda-app` module. Async retries stay at 0: **retries come from the schedule**, and
every run is idempotent.

| Schedule | Function | What it does |
|---|---|---|
| 16:30, 17:00, …, 22:30, 23:00 | **evening** | If it's not a session, or today's record is complete → no-op. Otherwise: fetch bars and universe (if no valid snapshot) → reconcile the session's fills from deal history → ledger → `plan()` → execute → write the record → summary to Telegram. At **23:00** with no valid data → degraded mode. One invocation after completion and after 20:00 runs the passive finality diff. |
| 09:35 | **open-exit** | Market-close the positions flagged in the latest record. Tolerate "already closed" (TP gap fill). Record the fills. |
| 09:50 | **morning-check** | Flagged positions are flat; every open btd position has a TP equal to the record's `T`; entry orders are live with the right expiry. Alert on any mismatch. |
| 23:15 | **heartbeat** | Alert if today's record isn't complete (the evening run never finished). |

Sizing: evening about 2 GB and a 10 min timeout (pandas + yfinance over 478 × 300). The others
use the defaults.

---

## 6. Orders and broker

### 6.1 Identity

- `label = "btd-<env>"` on every order (`btd-dev`).
- `clientOrderId`: `btd-<env>-<session YYYYMMDD>-<TICKER>-E` (entry) and `…-X` (open exit).
  The session is the session the order is for.
- **Nothing without our label is ever read for decisions or touched.** The other strategy on the
  account is invisible except through margin.

### 6.2 Order types

| Purpose | cTrader mechanism |
|---|---|
| Entry | `LIMIT` buy, `timeInForce = GOOD_TILL_DATE`, `expirationTimestamp` = 16:00 ET of the session (zoneinfo, DST-aware) |
| Target | The position's own take-profit, `ProtoOAAmendPositionSLTPReq`, every evening |
| Next-open exit | Market close of the position (by position id and volume) at 09:35 ET |

`plan()` returns **exact** `L` and `T`; execute rounds them to the symbol's `digits` (cents) when
it sends the order. Rounding inside the core would change backtest results on low adjusted
historical prices (NFLX 2011 ≈ $3, where a cent is about 0.3%).

### 6.3 Reconciliation (execute)

The plan describes the **desired state** for the next session: entry orders, the TP per position,
and flagged exits. Execute reads the btd-labeled orders and positions and applies the difference:

- place missing entry orders (looked up by `clientOrderId` first, so a retry never duplicates);
- cancel btd entry orders not in the plan, including leftovers from earlier sessions (backup to
  the GTD expiry);
- amend TPs that differ from the plan.

Running execute twice is a no-op.

**Anomalies alert and are never auto-fixed:**
- a btd position the records don't explain;
- a volume that doesn't match what was filled (for example, after a split);
- a btd position without a TP after execute;
- a flagged exit still open at the morning check;
- an order rejected by the broker.

A rejection for insufficient margin is logged as a skipped order and not retried.

### 6.4 Client

`btd/broker/client.py` is **copied from gtb** (`gold-tokyo-breakout/src/gtb/broker/client.py`)
and extended with:
- limit orders with GTD expiry;
- position SL/TP amend;
- the symbols list with volume specs;
- market close by position;
- deal history with commission and swap.

The cTrader client id, secret and token are read on every run from the platform's shared
`/platform/shared/ctrader-*`. btd never refreshes or copies the token.
`/btd/<env>/ctrader-account-id` is per env. The access token is re-read from SSM on every
invocation, not only at cold start (platform conventions § Secrets).

---

## 7. Ledger

The account is shared, so btd keeps a **virtual ledger** that behaves like a dedicated account.

- **Genesis:** at the first evening run (the supervised one, Phase 4), read the account **balance** once and
  freeze it as `start_capital`, with the timestamp, in `dev/ledger/genesis.json` (write-once).
  It's never re-read. (The API gives balance, not equity; any open position of the other strategy
  at that moment is left out, which is fine for a frozen constant.)
- **Deals carry no label** (only `positionId`/`orderId`), so they are attributed through the ids
  of every btd-labelled position a run has seen. Each btd position is open on at least one evening
  before it can close. The ids, the running peak and the −10% warning flag live in
  `dev/ledger/state.json`.
- **Recomputed every run from broker facts** (no mutable state):
  - `realized = Σ (gross P&L + commission + swap)` over deals with our label since genesis;
  - `unrealized = Σ volume · (Close[t] − entry price)` over open btd positions, marked at the
    snapshot's close;
  - `btd_equity = start_capital + realized + unrealized`;
  - `peak = max(btd_equity)` over the records; `drawdown = btd_equity / peak − 1`.
- Sizing, the gross cap and the drawdown alerts all use `btd_equity`. Commission and swap come
  from deal history, not from the account's configured rates.

---

## 8. Failure handling

| Situation | Behaviour |
|---|---|
| No valid bars by 23:00 ET | **Degraded mode:** no new entries; existing TPs stay as they are; the **time** exit is still applied (it only needs the calendar); the rebound exit is skipped that night; the record is marked `degraded` and excluded from signal parity; alert. |
| Universe sanity fails | Use the previous snapshot; alert. |
| Evening never completes | Heartbeat alert at 23:15. |
| Wrong account kind (dev on a non-demo account) | Refuse to run; alert. |
| Broker anomaly | Alert, leave the position as it is ([§6.3](#63-reconciliation-execute)). |
| Drawdown ≤ −10% | Warning alert (once, when crossed). |
| Drawdown ≤ −15% | Breach alert, **repeated every evening** while below. Trading continues. |

---

## 9. Alerts

- **App alerts and summaries go straight to Telegram**, through a project bot (copied from gtb's
  `alerts/telegram.py` and `messages.py`). Format: `ALERT [dev] <date>: …`. Secrets
  `telegram-bot-token` and `telegram-chat-id` are in SSM under `/btd/<env>/`.
- **Infra alarms** (Lambda errors) come from `lambda-app` → `platform-alarms` SNS → Telegram.
- **Evening summary** every session, also as a heartbeat on quiet days: equity, day change,
  drawdown, fills, exits with reason and return, tonight's entries (ticker, `L`, volume), TPs
  amended, flagged exits, slots used.
- **Open-exit confirmation**: each close with its fill price against the open.

---

## 10. Records and storage

The data bucket is the platform's `data-bucket` (versioned, append-only, no `DeleteObject`).
Under the env prefix:

| Key | Written by | Content |
|---|---|---|
| `dev/bars/<date>.parquet` | evening | The exact bar snapshot traded on |
| `dev/universe/<date>.json` | evening | Constituents, venue specs, the intersection, the scrape diff |
| `dev/ledger/genesis.json` | first run | `start_capital`, timestamp (write-once) |
| `dev/records/<date>.json` | evening, open-exit | The session record (below) |

**Session record** (§5.2 of the spec, plus what parity needs):
- **inputs:** the bars and universe keys, `degraded`;
- **ledger:** equity, realized, unrealized, peak, drawdown, slots used and free, gross notional;
- **candidates, every signal**, not only the ordered ones: ticker, `Close`, `ATR5`, `SMA200`,
  `DayRet`, `VolPct`, rank, and `ordered` or skip reason (`no_slot`, `cap_trim`, `min_size`,
  `held`);
- **orders:** `clientOrderId`, `L`, volume, broker id, status;
- **positions:** entry date and price, volume, `held`, tonight's `T`, flag and reason;
- **broker facts** for the session just ended, from deal history: fills with time and price,
  slippage against `L` / `T` / `Open`, commission, swap;
- **alerts sent.**

`trades.csv` is **derived** from the records by a script (never stored as a source of truth), in
Hermes's columns: `ticker, entry_date, exit_date, entry, exit, ret, why, volp, ret_sig, depth_atr,
mae, mfe`.

---

## 11. Validation

1. **Reference trades** (spec §4: META, EXPE, GLW, CF) are unit tests on the pure core, exact to
   the cent on the same bars.
2. **In-repo backtest.** It loops over sessions, calls the **same `plan()`** that the evening
   Lambda calls, and simulates fills with the backtest's rules (fill on a touch of `L` at
   `min(open, L)`, target at `max(open, T)`, next-open exits at `Open`). Its inputs are bars, a
   membership calendar and an optional venue list. It writes a trades CSV in Hermes's columns.
   - **Historical membership is `sp500_history.csv` at the repo root**: the exact file Hermes
     used (`date,tickers`; 2,720 snapshots, 1996-01-02 to 2026-08-18). It's gitignored and local
     only, so no CI test may depend on it.
   - Membership on day d is the latest snapshot dated ≤ d (`bisect_right`, as Hermes does).
     Dates after the last snapshot carry it forward.
   - The forward-period parity run uses our daily universe snapshots instead. **The
   user runs Hermes and compares.** That comparison is the gate before anything trades. Use the
   same bar files on both sides, because adjusted prices drift as dividends re-base history.
   After the gate, there's no link to Hermes.
3. **Monthly parity.** The btd backtest over the forward period, on the stored daily snapshots,
   against the derived live `trades.csv`. It reports:
   - signal match % (target ≥ 95%);
   - order match % (ticker, rank, `L`);
   - fill rate, live against simulated;
   - entry slippage against `L` (≤ 3 bp average), target slippage against `T`, open-exit
     slippage against `Open`;
   - mean trade after costs.

   A mismatch is a bug until proven otherwise.
4. **Decision rules:** spec §5.1, unchanged. About 100 trades before a verdict; continue if the
   mean after costs is > +0.3%; stop and review if it's ≤ 0, or (by human decision, see §3 #6)
   on a −15% drawdown.

---

## 12. Environments and infra

- Generated from the platform copier template: slug **`btd`**, package `btd`, no LLM,
  `deploy_lambda`.
- **Environments `dev` and `prod`** (a deliberate deviation from the template's `demo`/`live`, as
  in gtb). **Only `dev` is deployed**, against the shared Pepperstone demo account. `prod` exists
  as config only; there's no prod deploy job and no prod AWS resources until the user decides.
- A push to the `dev` branch deploys dev through the platform's reusable workflow (OIDC).
- SSM (kebab-case, platform convention): `/btd/dev/ctrader-account-id`,
  `/btd/dev/telegram-bot-token`, `/btd/dev/telegram-chat-id`
  (set by `scripts/put_secrets.py`). The cTrader app credentials and token are
  `/platform/shared/ctrader-*`.
- Region from `AWS_REGION`, default eu-west-1.

### 12.1 Code layout

```
src/btd/
  config.py              # load_env, secrets, env → account kind
  core/                  # PURE: no network, clock, env or AWS
    indicators.py        # §2.1
    signals.py           # §2.2 candidates and ranking
    sizing.py            # §2.3
    exits.py             # §2.5 target, rebound, time, removal
    plan.py              # plan(bars, universe, ledger, positions, calendar, session) -> Plan
  backtest/              # fill simulator + CLI; calls core.plan
  data/
    bars.py              # BarSource, YFinanceSource, validation, snapshot
    universe.py          # Wikipedia scrape, venue intersection, sanity
    tickers.py           # canonical ↔ yfinance ↔ cTrader
  broker/client.py       # from gtb, extended
  ledger.py
  records/               # record model and S3 store
  alerts/                # telegram.py, messages.py
  runs/                  # evening, open_exit, morning_check, heartbeat, app (handlers)
scripts/                 # put_secrets, trades_from_records, parity, spike/
```

---

## 13. Open questions (spike)

These are answered by the spike before the trading code exists. Item 3 is the **go/no-go** for
evening placement. **Results: [SPIKE.md](SPIKE.md).** The go/no-go passed: a GTD limit placed
while the market is closed is accepted, and the account is hedged.

1. **yfinance from Lambda (eu-west-1):** 478 × 300 days, `auto_adjust`, 5 sessions at 16:30 and
   17:00. Success rate, latency, missing names.
2. **Close finality:** the 16:30 close against the 20:00 close against the next day's close.
3. **cTrader on the shared demo account:**
   - hedging or netting? This matters if a time-exited ticker re-signals: the backtest re-enters
     it the next morning, and a buy limit that gap-fills before the 09:35 close would merge into
     the old position on a netting account;
   - is a GTD buy limit accepted **while the market is closed**?
   - does a TP amend work while closed?
   - does a TP fill at the open on a gap?
   - does GTD expire at 16:00 ET?
   - `minVolume` / `stepVolume` on a sample.
4. **Pepperstone D1 bars against yfinance:** session boundaries; the typical close difference,
   which sets the §4.1 cross-check threshold.
5. **The Wikipedia scrape** maps cleanly to the 478 venue symbols (`BRK.B`, `BF.B`, share classes).

---

## 14. Decision log

| # | Decision | Alternatives rejected |
|---|---|---|
| 1 | Signals from vendor bars, execution on the venue (hybrid) | Venue bars (no split adjustment, bid-based) |
| 2 | yfinance, fully adjusted | Tiingo/EODHD/Polygon (paid) |
| 3 | Lambda, with fetch as a replaceable stage; reliability spike first | Home machine |
| 4 | Orders placed in the **evening** | Pre-open execute run |
| 5 | Next-open exits by a separate open-exit Lambda (09:35 ET) | Marketable pending order placed in the evening |
| 6 | Shared USD demo account with a virtual ledger | New dedicated demo account |
| 7 | `start_capital` = account equity at the first run, frozen | Fixed constant |
| 8 | Wikipedia scrape for constituents, daily, with sanity guards | SPY holdings file, S&P DJI |
| 9 | First fetch 16:30 ET, retry every 30 min to 23:00; open-exit a few minutes after the open | 18:00 first fetch |
| 10 | Degraded mode A (no entries, stale TPs, time exit only) | Fallback venue bars; manual |
| 11 | Size at `L`, round down, conservative gross cap with the lowest rank trimmed first | Hermes-style sizing at the fill price |
| 12 | Label/clientOrderId identity, desired-state reconciliation, anomalies alert only | — |
| 13 | Port indicators from Hermes; in-repo backtest with a trades CSV; the user compares with Hermes; then no link | Ongoing Hermes judge; frozen fixture export |
| 14 | Copier template, slug `btd`, no LLM | — |
| 15 | Drawdown: alarms at −10% and −15%, no halt | Auto-halt entries; flatten |
| 16 | `dev`/`prod` envs; only dev deployed (demo); prod not deployed | `demo`/`live`; prod deployed but disabled |
| 17 | App alerts and summary via a Telegram bot (gtb pattern); infra alarms via `platform-alarms` | Everything through SNS |
| 18 | Session record JSON + raw snapshots in S3; `trades.csv` derived | — |
| 19 | One idempotent evening function, half-hourly; open-exit, morning-check, heartbeat | Separate fetch Lambda with an S3 trigger |
| 20 | cTrader client copied from gtb and extended | Shared platform `ctraderkit` |
| 21 | Build order: scaffold → spike → core and backtest → plumbing → dev on demo → parity | — |
