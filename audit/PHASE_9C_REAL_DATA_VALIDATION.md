# Phase 9C — Real-Data 1UP/2DOWN Opening-Range Validation

**Status: STOPPED at the mandatory real-data gate. Verdict: `DATA_UNAVAILABLE`.**

Per this phase's own explicit instruction — *"If real data cannot be
obtained: STOP the real-data experiment. Do not silently fall back to
synthetic data. Report: DATA_UNAVAILABLE and identify exactly which
datasets are missing."* — no Phase 9C strategy, structure, bias, entry,
SL/TP, risk, portfolio, backtest, ablation, mutation, or web-terminal work
was performed. Building any of that against synthetic data in a phase
explicitly scoped to real-data validation would be exactly the
"substitute synthetic results for real-market evidence" the authorization
prohibits. This document is the complete Phase 9C deliverable.

---

## 1. Governance capture (before any other action)

- **HEAD**: `a0818548a88d16059d1522a0ca654a1bbbd37884`
- **Branch**: `claude/multi-strategy-hedge-backtest-sa7cer`
- **Working tree**: clean, up to date with origin, before this document
  was added.
- **Production files** (`src/`, `public/`, `astro.config.mjs`,
  `package.json`, `package-lock.json`, `tsconfig.json`, 34 files):
  SHA-256 of every file diffed byte-for-byte against the Phase 9B
  baseline recorded the same session — **identical, zero drift.**
- **`.env`**: no `.env` file exists in this repository; nothing to hash.
- **`research/config.py`** (governs the DATA DISCLOSURE / synthetic-only
  posture): hashed and recorded (`fa6e0ec7...`) for future drift
  comparison.
- **Live-trading state**: unchanged — no MT5/broker code exists anywhere
  in this repository (re-confirmed in Section 4 below); `LIVE_TRADING =
  DISABLED`, as in every prior phase.

## 2. Real-data-first attempt — filesystem search

Searched the entire accessible filesystem (excluding `node_modules/`,
`.venv/`, `/proc`, `/sys`) for any locally-supplied historical price data:

```
find / -maxdepth 6 -iname "*.csv" -o -iname "*eurusd*" \
       -o -iname "*.parquet" -o -iname "*histdata*" -o -iname "*dukascopy*"
```

Matches: two OS package files unrelated to trading data
(`/usr/share/distro-info/{ubuntu,debian}.csv`) and two Phase-7-era
synthetic sample artifacts (`research/results/candles_eurusd_sample.json`,
`overlays_eurusd_sample.json` — both derived from
`research/data/synthetic.py`, not real data). `research/data/` contains
only loader/quality/synthetic *code* (`real_data.py`, `loaders.py`,
`quality.py`, `synthetic.py`) — no data files. No `data/` directory
anywhere else in the repository. **Zero real historical price data found
on disk.**

## 3. Real-data-first attempt — network probe (fresh, this session)

A fresh probe against 8 distinct real-market-data-relevant hosts, not a
citation of a prior phase's result:

| Host | Purpose | Result |
|---|---|---|
| `stooq.com` | free daily/intraday quotes | `000` — connection rejected |
| `query1.finance.yahoo.com` | Yahoo Finance intraday chart API | `000` — connection rejected |
| `www.histdata.com` | free historical FX tick/minute data | `000` — connection rejected |
| `raw.githubusercontent.com` | GitHub-hosted downloader script | `200` — reachable |
| `api.exchangerate.host` | daily FX rates API | `000` — connection rejected |
| `www.dukascopy.com` | historical FX data | `000` — connection rejected |
| `truefx.com` | free tick data | `000` — connection rejected |
| `www.forexite.com` | free daily FX archive | `000` — connection rejected |

This session's outbound proxy (`$HTTPS_PROXY/__agentproxy/status`) records
the exact rejection reason for each, structured and reproducible, not
inferred:

```
stooq.com:443                  gateway answered 403 to CONNECT (policy denial or upstream failure)
query1.finance.yahoo.com:443   gateway answered 403 to CONNECT (policy denial or upstream failure)
www.histdata.com:443           gateway answered 403 to CONNECT (policy denial or upstream failure)
api.exchangerate.host:443      gateway answered 403 to CONNECT (policy denial or upstream failure)
www.dukascopy.com:443          gateway answered 403 to CONNECT (policy denial or upstream failure)
truefx.com:443                 gateway answered 403 to CONNECT (policy denial or upstream failure)
www.forexite.com:443           gateway answered 403 to CONNECT (policy denial or upstream failure)
```

`raw.githubusercontent.com` being reachable was followed up, not assumed
useless: it served the `philipperemy/FX-1-Minute-Data` repository's
README, which turned out to be a *downloader script* whose actual data
sources are `histdata.com` (blocked above) and a Google Drive folder link
(Google Drive is not a code-hosting CDN and is not reachable through this
proxy for the same policy reasons). `github.com` itself (the web UI/API,
as opposed to the specific raw-content CDN) returned `403`. **No path
from the one reachable host led to actual real market data.**

## 4. Real-data-first attempt — credentials / sanctioned API access

Checked the environment for any pre-configured real-data API key or
broker credential (`OANDA`, `ALPHA_VANTAGE`, `POLYGON`, `DUKASCOPY`,
`MT5`, `METATRADER`, generic `*_API_KEY`, `FX`/`FOREX`/`MARKET_DATA`
patterns): **none found.** No sanctioned real-data access path exists in
this environment, confirming this is a deliberate org network policy, not
a fixable configuration gap. Re-confirmed no `import MetaTrader5`, no
`mt5.initialize`/`mt5.order_send`, no broker SDK, and no order-routing
code exists anywhere in `research/` or `web/` (only disclaimer text
mentions "MT5", consistent with every prior phase's audit).

## 5. Exactly which datasets are missing

Per the Phase 9C specification's minimum requirement — M1, M5, M15 for
each of the 6 preferred symbols — **all 18 required datasets are
missing**:

| Symbol | M1 | M5 | M15 |
|---|---|---|---|
| EUR_USD | missing | missing | missing |
| USD_JPY | missing | missing | missing |
| GBP_USD | missing | missing | missing |
| XAUUSD | missing | missing | missing |
| AUD_USD | missing | missing | missing |
| USD_CHF | missing | missing | missing |

No partial data exists for any symbol or timeframe. No dataset manifest,
SHA-256 registry, or data-quality audit was produced, since none of those
have any real content to describe — producing one against a placeholder
would misrepresent the data state.

## 6. What this means for the Phase 9C primary objective

The primary objective — *"Determine whether the Phase 9B 1UP/2DOWN
Opening Range framework contains a reproducible trading edge on REAL
historical market data"* — **cannot be evaluated in this environment.**
None of the 17 primary questions in the authorization (does 1UP/2DOWN
work on real data, which entry family is best, does structure/Fibonacci/
candle-pattern/significant-move add information on real data, which SL/TP/
risk level survives real costs, etc.) can be answered without committing
exactly the violation the authorization explicitly forbids: *"substitute
synthetic results for real-market evidence."* Phase 9B already answered
every one of these questions **on synthetic data** (see
`audit/PHASE_9B_OPENING_RANGE_MULTI_TIMEFRAME_ENGINE.md`) — those findings
stand as synthetic-validation evidence only and are not re-litigated or
extended here.

The engine itself remains real-data-ready: `research/data/real_data.py`'s
`load_real_ohlcv()`/`extended_quality_audit()`, every causal core module
(structure, regime, bias, Fibonacci, liquidity, candle anatomy, sessions,
protected levels), the full `opening_range_v2.py` state machine, and the
entire backtest/validation/mutation-testing stack built in Phases 7-9B
would accept real M1/M5/M15 OHLCV data with **zero code changes** the
moment it becomes available — this was true before Phase 9C and remains
true now; Phase 9C's job was to supply the data, not to rebuild the
engine, and the data did not arrive.

## 7. What would unblock this

Either of:

1. **The user supplies real historical OHLCV data directly** (file
   upload into this environment) for at least one of the 6 preferred
   symbols, at M1 granularity (M5/M15 can be derived from M1 by the
   existing `resample_ohlc`), matching the schema
   `research/data/real_data.py` already documents (`timestamp, open,
   high, low, close[, volume, spread, symbol]`, CSV or Parquet) — or any
   reasonably close schema, since `column_map` supports renaming.
2. **This environment's network egress policy is changed** to allow at
   least one genuine historical-data host (a specific broker export
   endpoint, a licensed data vendor API with credentials supplied via
   environment variable, etc.) — this is an infrastructure/account
   decision outside this session's control, not something any code change
   here can work around.

No other action in this session can produce real market data; further
attempts to route around network policy (proxies, mirrors, scraping
alternate hosts for the same underlying blocked data) would not
constitute "finding" real data — they would be the same blocked sources
by another name, and are not attempted.

---

## Final verdict

**`DATA_UNAVAILABLE`.**

**FILES_CHANGED**: this document only (plus two throwaway hash files in
`/tmp`, not part of the repository). No research, strategy, or web-terminal
code was written or modified in Phase 9C.
**PRODUCTION_IMPACT**: NONE (byte-identical hashes, verified, Section 1).
**LIVE_TRADING**: remains disabled; no MT5/broker/order-routing code
exists anywhere in this repository (re-verified, Section 4).
**DATA_USED**: none — this phase deliberately produced zero experimental
results rather than fabricate or substitute data.
**TESTS**: none run (no code changed to warrant it; Phase 9B's 15/15
mutation tests remain valid and were not re-run here).
**MISSING_DATASETS**: all 18 (Section 5).
**NEXT_SAFE_ACTION**: await either real historical data from the user or
a network-policy change (Section 7). Do not begin Phase 9D. Do not
attempt Phase 9C's strategy validation on synthetic data under any
framing — that would misrepresent Phase 9C's real-data objective, which
Phase 9B has already covered honestly under its own, correctly-labeled,
synthetic-validation scope.

**STOP after Phase 9C, per the authorization's explicit instruction.**
