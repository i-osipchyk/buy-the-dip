# Phase 1 spike: results

Answers to [ARCHITECTURE §13](ARCHITECTURE.md#13-open-questions-spike). Scripts are in
`scripts/spike/`, and raw outputs in `data/local/spike/` (gitignored). The shared demo account
was probed with orders labelled `btd-spike` only.

| # | Question | Status | Answer |
|---|---|---|---|
| 1 | yfinance from Lambda | **pending** (deploy) | Local baseline: 477/477 in 11.5 s, the latest bar complete for all. Lambda: `spike_fetch` at 16:30 and 17:00 ET once deployed |
| 2 | Close finality | **pending** (needs evening fetches) | — |
| 3 | cTrader behaviour | **go**; 3 checks pending | GTD limit while closed **accepted**; market order while closed **rejected**; account **hedged** |
| 4 | D1 against yfinance | **done** | D1 bars open 17:00 NY the evening before; regular session only; close −6 bp median |
| 5 | Wikipedia ∩ venue | **done** | 477 names; the venue spells share classes inconsistently |

---

## 1. yfinance (and Wikipedia) from AWS

- **Local baseline (2026-10-16 04:25 ET):** `yf.download` of 477 tickers, `period=15mo`,
  `auto_adjust=True`: 11.5 s, 477/477 tickers, about 316 rows each, 2026-10-15 complete for all.
  A second local run over all 503 constituents took 19 s, with 503/503.
- **Lambda:** pending. The dev infra has a read-only function `btd-dev-spike_fetch` (Wikipedia
  scrape + yfinance download of every constituent, results in the log line `SPIKE {...}`),
  scheduled at 16:30 and 17:00 ET on weekdays. It needs the repo wired and deployed (the commands
  are in the session notes). Pass: ≥ 9/10 runs with ≥ 98% of tickers and the day's bar present.

## 2. Close finality

Pending. Fetch at 16:30 ET, 20:00 ET and the next day, then
`compare_closes.py --date <session> <tag-1630> <tag-2000> <tag-next>`. The question is whether
the 16:30 `Close` differs from the settled one (and by how much), which decides whether the
evening run may plan on 16:30 data.

## 3. cTrader on the shared demo account

`scripts/spike/probe.py`, stage `closed` at 2026-10-16 04:27 ET (market closed):

| Check | Result |
|---|---|
| Account mode | **hedged.** Positions don't net, so a re-entry on the morning of a time exit opens a separate position (the ARCHITECTURE §2.2 concern is gone) |
| GTD buy limit placed **while closed** | **Accepted** (order 74543319, AAPL.US @ 274.10, expires 16:00 ET). **Evening placement is a go.** |
| Market order while closed | **Rejected: `MARKET_CLOSED`.** This confirms the 09:35 open-exit Lambda (decision 5) |
| Volume specs (AAPL, BRK.B, BF-B, META, NVR) | lot size 100, step 10, min 10 for all: 0.1-share steps, volume in 1/100 share |
| GTD expiry at 16:00 ET | pending: stage `evening` |
| TP amend while closed; TP below the market | pending: stage `evening` |
| TP gap fill at the open price | pending: stage `next` |

## 4. Pepperstone D1 against yfinance

`scripts/spike/d1_vs_yf.py`, 40 names (10 fixed + 30 random), about 48 sessions, against
yfinance **raw** (`auto_adjust=False`) bars:

- **A D1 bar opens at 17:00 America/New_York the evening before the session it holds** (an FX-style
  rollover: the bar opening Sunday 17:00 is Monday's session). Session date =
  `(open time in NY + 7 h).date()`. With that mapping, all 1920 bars matched.
- The venue high is never above the official high by more than 17 bp, so the CFD bar covers
  **only the regular session**.
- Differences, venue against official, in bp:

  | | median | 5% | 95% | worst |
  |---|---|---|---|---|
  | Close | −5.9 | −36.5 | +13.8 | −112 (ACN) |
  | Open | −30.9 | −123.5 | +42.7 | −275 |

  The venue close is the 16:00 bid, not the closing auction. The venue open is the first quote,
  typically **below** the official open, which matters for the 09:35 open-exits (judged against
  the official `Open`).
- **Cross-check threshold** (ARCHITECTURE §4.1): log a name when `|venue − yfinance| > 150 bp`;
  alert when more than 5% of names exceed it. 1% would trip on normal days (ACN −112 bp).

## 5. Wikipedia ∩ venue

`scripts/spike/universe_check.py` (Wikipedia fetched 2026-10-16, venue list 6462 symbols):

- 503 constituents, 781 venue shares (`<X>.US`), **universe 477**. Not on the venue (26): APP
  ARES BE CASY CIEN COHR ECHO EG EME FDXF FERG FIX FLEX HONA IR LITE P Q RDDT RMD SKYD SNDK TWLO
  VEEV VMRK VYLR.
- **The venue spells share classes inconsistently:** `BRK.B.US` but `BF-B.US`. The
  canonical→venue map therefore comes from the venue list (`from_venue`), not from a rule. Variants
  to ignore: `-24`, `-24_SB`, `-24_SBE`, `-PERP`, `-PERP_SB`, `_SB`, `_SB2`, `_SBE`.
- Against Hermes's list of 478 (`pepperstone_sp500_available.csv`):
  - **`BF.B` is tradable but not in Hermes's list**, probably because of the dash spelling. It
    was never in the backtest. One name out of ~478, so the impact on the yardstick is negligible.
  - `DASH`, `ZTS` (and `ILMN`, added since) are in btd but not in Hermes's list, although both
    are members and on the venue.
  - `BLDR`, `CTVA`, `TAP`, `TTD`, `WBD` are in Hermes's list but have left the index since the
    last snapshot in `sp500_history.csv` (2026-08-18).
