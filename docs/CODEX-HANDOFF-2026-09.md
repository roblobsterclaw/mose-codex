# 🦞 MOSE — Build Handoff for ChatGPT Codex (September 2026)

*Prepared 2 Sep 2026 for Joe Lynch. Written so a second builder (Codex) can work on MOSE in
parallel with Claude Code without either side breaking the other's work. Read all of it before
touching a file. The earlier `CODEX-PROMPT.md` (May 2026) is historical; this document
supersedes it.*

Repo: `https://github.com/roblobsterclaw/mose` · Live: `https://roblobsterclaw.github.io/mose/`
Owner: Joe Lynch (GitHub `roblobsterclaw`). Wife: Keli. Mac Mini agent: "Hermes".

---

## 0. Ground rules (standing, from Joe — not negotiable)

1. **Accuracy over speed.** Never display invented data. If a number can't be sourced, show
   "not loaded" and say why. Family money rides on this.
2. **Develop on `main`.** Deploy = the `update-live-market-data.yml` Action force-pushes
   `main` → `gh-pages`. **Never open a pull request unless Joe asks.** Never push to other
   branches without permission. For parallel work, Codex uses branches named `codex/<topic>`
   and Joe merges; see §7.
3. **Never execute a trade.** Agents may *stage* nothing and *execute* nothing. Every buy is
   entered by Joe by hand in IBKR after printing the buy list. Read-only brokerage access only.
4. **The 8-bucket taxonomy is locked** (§4.4). Do not rename, add or remove buckets. Tickers
   inside buckets are editable in-app by Joe only.
5. **13F filers are the only voice in stock selection.** Creators (YouTubers, newsletters) and
   any non-filer source are *provenance only*: they may tag where an idea came from, never feed
   a score, a ranking, a bucket or a calculation. `IDEA_ORIGIN` in `index.html` is the pattern.
6. **Versioned client-side migrations.** `targetsData` (v12) and `reentryData` (v3) live in
   localStorage + Firebase. Any schema change bumps the version and **preserves `owned` and
   `plan` values**. Never wipe user state.
7. **No model identifiers** (Claude/GPT version strings) in commits, code or comments.
8. Joe dislikes repeated questions. Decide sensible defaults, state them, move on.

---

## 1. What MOSE is today (state as of 2026-09-02)

A single-file static dashboard (`index.html`, 7,746 lines, vanilla JS/CSS, no build step) on
GitHub Pages. It reads JSON files committed to the repo by two GitHub Actions and syncs Joe's
own state across devices through Firebase Realtime Database
(`https://jfl-ttd-default-rtdb.firebaseio.com/mose`).

**Tabs (6 groups, `TAB_GROUPS` at `index.html:2907`):** Command Center · Super Investors
(holdings, consensus, filing changes) · Watchlist / Buy Zone · Buy Targets (three accounts,
eight buckets) · Re-Entry Plan · Research Library (77 hand-written deep dives).

**Accounts modelled:** Joe's IRA (~$950k, key `his`), Keli's IRA (~$200k, key `hers`), Joint
Cash (~$344k, key `joint`). One shared bucket set; per-stock $ target = account size × bucket
% × stock's share of bucket, auto-split ~63.6 / 13.4 / 23 %.

**Current posture:** ~90% in SGOV (T-bills) since 30 Mar 2026. Re-entry plan: four monthly
tranches from **15 Sep 2026** (IRAs 100% = $1,150,000; Joint 50% = $172,000), with a
$172,000 "ALL-IN" reserve armed at −8% from the S&P reference high, hard deadline 1 Aug 2027.

**Pipelines:**
- `update-live-market-data.yml` — every 5 min in market hours, hourly otherwise. Runs
  `scripts/update_live_market_data.py` → `live-quotes.json`, `symbol-snapshots.json`,
  `price-history.json`, `pipeline-status.json`. Commits to `main`, force-pushes `gh-pages`.
- `update-13f-tracker.yml` — daily in filing months (Feb/May/Aug/Nov), weekly otherwise.
  `pull_sec_13f_history.py --quarters 8` → `build_13f_tracker.py` →
  `build_ticker_directory.py` → `build_holdings_from_13f.py` → optional Supabase sync.
  Writes `data/sec-13f-filings.json`, `filing-changes-latest.json`, `holdings-latest.json`,
  `reference-data/ticker-directory.json`.

**Things that exist but are not on the critical path:** `scripts/mose_db.py` + `db/schema.sql`
(SQLite "truth store" scaffold, May 2026); `supabase/` (13F sync only, the front-end never
reads it); `adapters/` (read-only brokerage placeholders); `pull_13f.py` (older puller);
`deploy.sh` (manual deploy, superseded by the Action).

**IBKR:** reached from Claude sessions via an MCP connector (positions, quotes, watchlists,
price history). Joe's login sees his IRA + Joint. Keli's IRA is a separate login. Eight IBKR
watchlists named after the buckets already exist (ids 108–115).

**Email:** `scripts/daily_buyzone_email.py` + `run_buyzone_cron.sh` send the daily Buy Zone
report; Hermes on the Mac Mini handles the formatted PDF version.

---

## 2. Repo map

| Path | Size | What it is | Written by |
|---|---|---|---|
| `index.html` | 422 KB | The whole app | humans/agents |
| `CLAUDE.md` | 5 KB | Standing context for Claude sessions. **Read it.** | Claude |
| `BUILD-LOG.md` | 22 KB | Session-by-session build log (Codex sessions 1–9, May–Jun 2026). **Keep appending.** | Codex/Claude |
| `CODEX-PROMPT.md` | 9 KB | May 2026 original build brief. Historical. | — |
| `SYNC-INVESTIGATION-REPORT.md` | 19 KB | Why localStorage didn't sync; led to Firebase. | Claude |
| `docs/ARCHITECTURE.md`, `docs/DEEP-DIVES.md`, `docs/SECURITY-LOCKDOWN.md` | | Design notes | |
| `reference-data/MOSE.md` | 25 KB | Master playbook, branding, investor tiers | Hermes/Joe |
| `reference-data/MOSE-DATA-PROTOCOL.md` | 4 KB | **Data tiers + quality rules, approved by Joe 16 Apr 2026.** | Joe |
| `reference-data/cik-map.json` | 4 KB | The 29 tracked filers: name, fund, tier, CIK. Ackman = CIK 2026053 (moved from 1336528). | Claude |
| `reference-data/ticker-map.json` | 0.5 KB | Hand-verified CUSIP→ticker overrides (19 entries) | Claude |
| `reference-data/ticker-directory.json` | 965 KB | 15,358 US symbols `{t,n,e}` for search | Action |
| `reference-data/convergence-master.json` | 200 KB | Legacy convergence export (May). Superseded by `holdings-latest.json`. | mose_db.py |
| `reference-data/exit-baseline.json` | | S&P level at Joe's 30 Mar exit (6591.90) | Claude |
| `data/sec-13f-filings.json` | 10 MB | **Raw 13F history: 29 investors × 8 quarters, CUSIP-keyed.** | Action |
| `filing-changes-latest.json` | 8.8 MB | Quarter-over-quarter changes (Q2 vs Q1) + per-investor positions | Action |
| `holdings-latest.json` | 99 KB | Curated latest holdings, 24 investors, 37 tickers, with convergence/conviction fields | Action |
| `investors.json` | 9 KB | Investor profile cards | manual |
| `joes-holdings.json` | 6 KB | Joe's positions (stale — IBKR is truth) | manual |
| `dcf-latest.json` | 106 KB | DCF intrinsic values (several broken; see §5) | build |
| `live-quotes.json` | 53 KB | 182 tickers: price, prev_close, change_pct, 52w hi/lo | Action |
| `price-history.json` | 2.5 MB | Daily OHLCV, 49 tickers, **ends 2026-06-17 — stale** | Action |
| `symbol-snapshots.json`, `indices-latest.json`, `pipeline-status.json` | | Quote metadata, indices, pipeline health | Action |
| `research-library.json` + `deep-dives/*.html` | | 77 hand-authored reports, versioned per ticker | Claude |
| `truist-baseline-feb2026.json` | 37 KB | Pre-exit Truist book, 192 positions, $1,046,035.43 at 2026-02-28, plus fee block (1.19%/yr) | Claude |
| `data/watchlist-buckets.json`, `data/watchlist-notes.json`, `data/deep-dive-requests.json` | | User-state exports | app |
| `scripts/*.py` | | See §1 pipelines | |
| `.github/workflows/*.yml` | | The two Actions | |

**Files the app fetches at load** (grep `fetch(` in index.html): `dcf-latest.json`,
`filing-changes-latest.json`, `holdings-latest.json`, `indices-latest.json`,
`joes-holdings.json`, `live-quotes.json`, `pipeline-status.json`, `price-history.json`,
`reference-data/ticker-directory.json`, `research-library.json`, `symbol-snapshots.json`,
and `index.html?v=` (self-check for stale cache via `APP_BUILD`).

---

## 3. `index.html` map (line numbers as of 2026-09-02)

| Line | Symbol | Purpose |
|---|---|---|
| 2047 | `APP_BUILD` | Bump on every deploy; `checkForAppUpdate()` compares against the served file to beat phone cache |
| 2173 | `IDEA_ORIGIN` / 2200 `ideaOriginChip()` | Provenance chips for non-13F ideas (HHH, LOAR, TPL…) |
| 2654 | state load | localStorage + Firebase merge; `migrateTargets`, `migrateReentry` |
| 2717 | `moseFbPutDebounced()` | Firebase write path |
| 2907 | `TAB_GROUPS` / 2955 `switchTab()` | **Add new tabs here** |
| 3134 | `HOLDINGS_MIN_INVESTORS = 5` | UI filter on holdings table; `holdingsSnapshotSave/Load` = thin-quarter fallback |
| 3411 | `investorsCell()` | Collapsed investor badge pill |
| 3434 | `dcfSuspect()` | Flags DCF IVs outside 0.4×–3× price as unreliable |
| 3481 | `renderHoldings()` | Super-investor holdings table |
| 3675 | `CONSENSUS_MIN_INVESTORS = 2` / 3684 `consensusRows()` / 3711 `renderConsensus()` | Consensus tab |
| 4172 | `canonicalBucketMap()` | **Single source of truth for ticker→bucket**; invalidated on edit |
| 4855 | `renderWatchlist()` | |
| 5577 | `defaultReentryData()` / 5634 `migrateReentry()` / 5704 `reentryAllInState()` / 6042 `renderReentry()` | Re-entry plan (v3) |
| 6141 | `canonTargetsBuckets()` | **The locked taxonomy** |
| 6189 | `defaultTargetsData()` / 6226 `migrateTargets()` | Targets v12 |
| 6757 | `BUYZONE_THRESHOLDS` / 6774 `buyZoneRows()` / 6798 `renderBuyZone()` | Buy Zone (52-week position, cheapest first) |
| 7384 | `renderTargets()` | Buy Targets page + printable per-account order sheet |

Mobile: `@media (max-width: 560px)` with `.hide-sm`; keep tables inside `overflow-x:auto`.
Verification convention used so far: `node --check` on the embedded JS, small Node unit tests,
headless Chromium render (`--headless --dump-dom` / `--print-to-pdf`). Record steps in
`BUILD-LOG.md`.

---

## 4. Data schemas (abridged — open the files for the full shape)

**4.1 `data/sec-13f-filings.json`**
```
{ generated_at, source, quarters_requested, investor_count, filings_pulled, failed_investors,
  investors: [ { name, fund, tier, cik, source_type:"13F",
                 filings: [ { form, company, cik, filing_date, file_name, accession, period_end,
                              quarter:"2026-Q2", submission_url, total_value, num_holdings,
                              holdings: [ { ticker|null, identifier, cusip, company,
                                            market_value, shares, rank, pct_portfolio } ] } ],
                 filing_errors: [] } ] }
```
Caveat: `market_value` in this raw file appears ×1000 (13F legacy "thousands" scaling);
`holdings-latest.json` `value_usd` is correct dollars. **Key on `cusip`, never on `ticker`**
— ticker resolution varies between quarters and produces phantom exits otherwise.

**4.2 `holdings-latest.json`** — `holdings[]` rows: `ticker, company, investor, fund, shares,
value_usd, pct_portfolio, current_price, entry_quarter, entry_price, unrealized_pct, trend
(NEW/ADD/HOLD/TRIM), hold_duration, convergence_score, conviction`.

**4.3 `filing-changes-latest.json`** — `changes[]`: `ticker, cusip, company, investor, fund,
quarter, previous_quarter, change_type (new/add/trim/exit), shares, previous_shares,
market_value, pct_portfolio, filing_date`. Currently 2,514 rows, **2,375 with unresolved
tickers (`CUSIP:…`)** — CUSIP resolution is the weak link; see §6 Layer 2.

**4.4 Targets (`targetsData`, v12)** — `ira.accounts.{his,hers,joint}` with size and
overrides; shared `ira.buckets[]` = `{id, label, pct, tickers[], weights{}, locked{}}`;
`owned` and `plan` keyed `account|ticker`. The locked buckets and starting %:
Forever compounders 35 · Toll booths 10 · Hard assets 10 · AI core 8 · AI bench 4 ·
Opportunistic 8 · Radar 5 · Dry powder 20. Tickers per bucket: see `canonTargetsBuckets()`.

**4.5 Re-entry (`reentryData`, v3)** — `settings{referenceHigh, exitLevel, allIn{reserveAmount,
triggerDd, deployedAt}, reserveDeadline}`, `plans[]{id, totalAmount, months, startDate,
buyDay, allocations{bucket:pct}, ladder[{dd,mult}]}`, `purchases[]`.

**4.6 `reference-data/cik-map.json`** — array of `{name, fund, tier, cik}` (29). Add investors
here; the Action picks them up.

**4.7 `live-quotes.json`** — `{generated_at, source, market_status, indices[], quotes[]}`;
`quotes[]` = `{ticker, symbol, price, prev_close, change_pct, date, time, volume, week52_high,
week52_low}`. BRK.B is stored as `BRK-B`.

---

## 5. Known data caveats (do not present these as fact)

- **Ackman book is ~74% covered** in `holdings-latest.json` (8 positions); NFLX/HHH/PSUS rows
  are absent. Trend shows "NEW" for everything because of the CIK migration. Needs a re-pull.
- `holdings-latest.json` carries only **37 unique tickers across 24 investors** — it is a
  curated subset, not the full book. `data/sec-13f-filings.json` is the full book.
- `price-history.json` stops at **2026-06-17** and covers 49 tickers.
- **CVNA & ROP**: live price conflicts with DCF reference price. **KMX** DCF (~$9) not credible.
  **TSM/BABA** ADR-FX mis-scaled, **TSLA** auto-only. Treat all DCF as ⚠️ unless `dcfSuspect()`
  passes.
- **ASM** in the watchlist = Avino Silver & Gold, not ASM International.
- **SPCX** (SpaceX) began trading June 2026 — no history before that.
- **CSU** = Constellation Software, Toronto, CAD. IBKR conid 39194759. `BRK.B` is `BRK B` on IBKR.
- The Opportunity-Delta figure previously reported (−19.45% / −$227,304) compared a
  whole-household counterfactual to an IBKR snapshot that excludes Keli's IRA; it overstates.

---

## 6. The build (what Joe asked for, 2 Sep 2026)

Joe's words: *"a bigger super-value-investor list, pull all their holdings every quarter, build
my list only from stocks someone on that list owns — those are the guard rails — then connect
every social outlet, every interview, every letter, daily, so I know when things are changing
before the next 13F… and an agent for each stock I own and each investor I follow."*

Target scale: ≤20 positions, ≤15 followed investors "at the end", but the universe of eligible
investors should be built from evidence, then pruned.

### Layer 1 — Universe builder (quarterly)
**Input:** SEC bulk *Form 13F Data Sets* (one zip per quarter: SUBMISSION, COVERPAGE,
INFOTABLE, …; ~8,000 filers, ~3–4M holding rows). URL pattern:
`https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets`. Requires a
`User-Agent` header with a contact email per SEC rules.
**Screen** (defaults, tune later): position count ≤ 50; total value $300M–$50B; turnover across
the last 8 quarters ≤ 25 %/qtr; median hold ≥ 6 quarters; exclude names matching
bank/trust/pension/index/quant/insurance patterns. Score each survivor 0–100 on
concentration, patience, and drawdown behaviour.
**Output:** `reference-data/investor-universe.json`
```
{ generated_at, quarter, candidates:[{cik, name, fund, positions, total_value_usd,
  turnover_8q, median_hold_q, score, status:"candidate"|"approved"|"rejected", approved_at}] }
```
Approved entries also get appended to `cik-map.json`. **Joe approves every addition.** Expect
the approved list to settle at 60–80; beyond ~100 consensus is noise.

### Layer 2 — Holdings + conviction (quarterly, extends the existing tracker)
- Pull every approved filer's full book, CUSIP-keyed (`pull_sec_13f_history.py` already does
  this per CIK; the bulk dataset is the faster path once the universe is >50).
- **CUSIP→ticker at scale:** build `reference-data/cusip-map.json` from OpenFIGI
  (`https://api.openfigi.com/v3/mapping`, free tier, rate-limited) seeded with
  `ticker-map.json`. Mark ETFs/funds, foreign lines and unresolved CUSIPs explicitly.
- **Conviction score per ticker** = f(#approved holders, each holder's % of book, add/trim
  trend, hold duration, holder score from Layer 1). Emit `consensus-latest.json`:
```
{ generated_at, quarter, universe_size, rows:[{ticker, cusip, company, holders, holder_names[],
  max_pct_book, sum_pct_book, new_count, add_count, trim_count, exit_count, avg_hold_q,
  conviction, in_bucket }] }
```
- **Eligible universe** = every ticker with ≥1 approved holder → `eligible-universe.json`
  (ticker list + holders). **App rule:** Watchlist/Buy Targets flag any ticker not in the
  eligible set and refuse to route it into a bucket until Joe overrides with a reason.

### Layer 3 — Between-quarter signals (daily)
Two sources, kept separate in the data:
- **Fast filings (EDGAR, structured):** 13D/13G (5% crossings, days not months), Form 4 for
  investor-directors (e.g. Ackman at HHH), 13F/A amendments, and **N-PORT monthly holdings**
  for investors that run mutual funds (Fundsmith, Akre Focus, Oakmark, Sequoia, Dodge & Cox).
  EDGAR full-text search: `https://efts.sec.gov/LATEST/search-index?q=...`.
- **Words:** fund letters (fund websites), interviews (YouTube, podcasts), X posts for the
  few who post, Substack. Collected by the Mac Mini (residential IP; YouTube throttles cloud
  IPs), transcribed, then passed through an LLM extractor into structured signals.
**Output:** `signals/feed-latest.json`
```
{ generated_at, items:[{ id, ts, kind:"13D"|"13G"|"FORM4"|"13F_AMENDMENT"|"NPORT"|"LETTER"|"INTERVIEW"|"POST"|"NEWS",
  investor, ticker, direction:"bullish"|"bearish"|"add"|"trim"|"exit"|"new"|"neutral",
  confidence:0..1, quote, source_url, source_title, extracted_by }] }
```
**Rule:** signals from approved investors' own words raise a ticker's *watch* flag and appear in
the feed and the daily email. **Only filings move the conviction score.**

### Layer 4 — Social overlay (last, lowest signal)
LunarCrush (connector) mention volume + sentiment per ticker → `signals/social-latest.json`.
Display only. Never feeds a score.

### Layer 5 — One agent per position, one per investor (daily)
See §8 for the design. Outputs: `dossiers/stocks/<TICKER>.md`,
`dossiers/investors/<slug>.md`, and rows appended to `signals/feed-latest.json` with
`kind:"AGENT"` plus a `severity` field.

### Build order and acceptance
| Phase | Deliverable | Done when |
|---|---|---|
| 1 | Layer 1 on Q2-2026 bulk data; candidate list to Joe | `investor-universe.json` exists, ≥100 scored candidates, Joe has approved a first batch |
| 2 | Layer 2 on the approved list; `cusip-map.json`; `consensus-latest.json`; eligibility guard in app | ≥95% of approved holders' US equity value resolves to tickers; app blocks non-eligible tickers |
| 3 | Layer 3 fast filings | 13D/G, Form 4, N-PORT rows appear in the feed within 24h of EDGAR |
| 4 | Layer 3 words + Layer 5 agents | Daily email carries feed + agent change reports; silent days stay silent |
| 5 | Layer 4 | Social column on the consensus table |

---

## 7. Working in parallel with Claude Code — division of labour

To avoid two builders editing the same 422 KB file:

| Codex owns | Claude owns | Shared contract |
|---|---|---|
| `scripts/` new pipeline code (Layers 1–5), new workflows, `dossiers/`, `signals/`, `reference-data/investor-universe.json`, `cusip-map.json`, `consensus-latest.json`, `eligible-universe.json` | `index.html` (tabs, guard rail, feed UI), `research-library.json`, deep dives, `CLAUDE.md`, daily email | The JSON schemas in §6. Change a schema only by editing this document first and bumping `schema_version` in the file |

- Codex works on `codex/<topic>` branches; Joe merges to `main`. Claude commits to `main`
  directly per Joe's standing rule. Rebase before you push.
- Data files written by the Actions (`live-quotes.json`, `holdings-latest.json`, …) are
  **never hand-edited**; they will be overwritten within minutes.
- Append a dated session entry to `BUILD-LOG.md` for every session (what, verification steps,
  deploy status). This is how the two sides stay informed.
- Secrets: `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` exist as Actions secrets. Add
  `OPENFIGI_API_KEY`, `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`, `LUNARCRUSH_API_KEY` the same
  way. Nothing secret goes in the repo — it is public.
- Network: Claude's cloud sandbox is on the "Trusted" allowlist (SEC, YouTube, IBKR web are
  blocked until Joe switches it to Full). The **GitHub Action runner reaches SEC, Firebase,
  Stooq, Nasdaq**. The **Mac Mini** has a home IP and is the right place for YouTube/podcast
  collection.

---

## 8. Design: an agent per position, an agent per investor

"An agent per X" is a good mental model and a bad process model. Don't run 35 always-on
agents; run **one scheduler that executes a per-entity job**, where each entity has its own
persistent memory. That gives you the same behaviour at a fraction of the cost and with one
place to debug.

**Per entity (ticker or investor):**
- **Dossier** = the agent's memory: `dossiers/stocks/AAPL.md` /
  `dossiers/investors/bill-ackman.md`. Sections: thesis (why we own / why we follow), key
  metrics with last values, watch items with thresholds, last-known state, open questions,
  change log. The agent reads it first and rewrites it last, every run.
- **Daily run:** collect → diff against dossier → decide materiality → write.
  - *Stock collect:* EDGAR (8-K, 10-Q/K, Form 4, 13D/G on the ticker), earnings calendar,
    IBKR quote + volume vs 20-day average, news search for the ticker, transcripts if an
    earnings call happened, and any feed items naming the ticker.
  - *Investor collect:* EDGAR by CIK (any form), fund website letters page, YouTube/podcast
    watch for the name, X account if any, N-PORT if applicable, news search for the name.
- **Materiality gate** (defaults): guidance change; insider sale > $1M; any 13D/G; an approved
  investor mentions the name; price move > 2× sector move; earnings within 5 days; dividend or
  buyback change; for investors: any new filing, letter, or interview. If nothing trips,
  the run writes nothing and sends nothing. **Silence is the normal output.**
- **Output when something trips:** one row in `signals/feed-latest.json` (`kind:"AGENT"`,
  `severity: info|watch|act`), one line in the daily email, and an updated dossier.
  `act` also triggers a push/Telegram alert via Hermes.

**Scale and cost:** 20 positions + 15 investors = 35 runs/day. Each run is a few tool calls
and one LLM pass over maybe 20–50k tokens. Order of $5–15/day at retail API prices; less with
caching. Runs sequentially in under an hour on the Mac Mini or as a scheduled cloud session.

**Guardrails:** read-only everywhere; never place, stage or suggest an order; every claim in a
dossier carries a source URL and a date; dossiers are committed to the repo so Joe can read
them like a notebook; an agent that can't reach a source says so rather than guessing.

**Where it runs:** the Mac Mini (Hermes) is the default — always on, home IP for YouTube,
already has Telegram. Alternative: a scheduled cloud session (Claude Code routines or an
OpenAI equivalent) once the sandbox network is open, with the Mac Mini doing only the
YouTube pull.

---

## 9. Context numbers (so nobody re-derives them)

- Truist pre-exit book: $1,046,035 (28 Feb 2026), 192 positions, 4 accounts. Fees 1.19%/yr
  = $12,276/yr.
- Counterfactual, Truist book held 27 Feb → 25 Aug 2026: +11.72% gross, **+11.07% net of fees**
  ($1,161,852). S&P (VOO) same window +11.57%.
- Joe's own 8-bucket plan, same window, lump sum: **+8.68%** ($1,136,831) — trailed the managed
  book by 2.4 pts. From 17 Apr: +4.71%. T-bills (actual): ~+2.06%.
- Lesson recorded: being out of the market cost ~6.6 pts vs his own plan; the manager was not
  the problem.
- IBKR snapshot (Joe's login, 26 Aug): $941,370 total, SGOV $845,460 (89.8%).
- Q2-2026 13F: multi-filer new buys SPCX (7), CBRS (7), V/SPGI/NFLX/SNOW/GOOGL (3 each).
  **NFLX** appears as a 3-filer new buy in both Q1 and Q2 and is in no bucket → Radar candidate.
- Ackman Q2 book (8 disclosed positions, 73.7%): UBER, BN, MSFT, AMZN, META, V, MA, SPGI —
  all already in Joe's buckets.

---

## 10. What Joe has decided (don't re-ask)

- Hold August; re-entry starts 15 Sep 2026. "Leave plan as is for now."
- Reserve trigger stays at −8% (a move to −15% was proposed and declined for now).
- Bucket %s unchanged. AI bench trimmed 17 → 4 (AMD, ARM, MU, COHR). DIS, TDG, COF → Radar.
- The Bald Investor is an approved *creator source* (provenance only).
- Automated snapshots are ON HOLD until Joe says go.
- Advisor research (Interactive Advisors vs independent RIAs at IBKR): research only, nothing
  opened. Requirement: must be able to phone a human.

*End of handoff.*
