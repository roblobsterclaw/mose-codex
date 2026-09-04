# 🦞 MOSE Dashboard — BUILD LOG
**Project:** MOSE — Margin of Safety Engine  
**Owner:** Joe Lynch  
**Kicked off by:** Hermes (via Telegram), May 7, 2026  
**Codex model:** GPT-5.5  

---

## Session 11 - September 4, 2026 (Independent build)
**Goal:** Create a separate MOSE implementation and begin the selective Top 50 super-investor system without changing production MOSE.

**Repository boundary:**
- Created the standalone `roblobsterclaw/mose-codex` repository from the current production snapshot.
- Changed the app and quote collector to the separate `/mose-codex` Firebase namespace.
- Added isolated `mose_codex_*` Supabase tables. No production table or live URL is targeted.

**What was built:**
- An explicit qualification policy with hard gates for portfolio size, position count, turnover, holding age, filing history, and long-only representation.
- A quarterly SEC bulk 13F universe scorer that handles restatements and additive amendments, keys history by CUSIP, preserves incumbents, and refuses to publish below the configured candidate minimum.
- A Joe-only decision ledger and safe approval command. Rejections deactivate a CIK without deleting history.
- A four-times-daily approved-investor monitor for SC 13D/G, Form 4, 13F amendments, N-PORT entities, and verified first-party RSS/Atom sources.
- A source-backed feed contract that leaves unknown ticker and direction values unresolved.
- A new Top 50 app tab for approved investors, ranked candidates, failed gates, and exportable pending review choices.
- Separate GitHub Actions for quarterly universe scans and investor signals, plus a Supabase sync adapter and migration.

**Verification:**
- Six unit tests cover amendment merging, CUSIP-weight turnover, eight-quarter candidate scoring, exclusion gates, Form 4 net transactions, and unresolved 13D fields.
- All Python files compile, embedded dashboard JavaScript parses, workflow YAML parses, and `git diff --check` passes.

**Deployment status:**
- Independent repository created. Production `roblobsterclaw/mose` remains untouched.
- First SEC universe and monitoring runs were attempted from GitHub. SEC returned HTTP 403 to both the bulk-data and submissions endpoints; the jobs surfaced the outage and did not fabricate results.
- Published a clearly labeled tracked-only bootstrap from the committed 29-investor, eight-quarter history. It nominates zero new candidates and will be replaced by the full universe export when an SEC-capable collector is connected.
- Supabase migration is ready; the independent repository does not yet have Supabase secrets.

## Session 10 — September 2, 2026 (Claude)
**Goal:** Start the "guard rails + feed" build Joe asked for (see `docs/CODEX-HANDOFF-2026-09.md`): only stocks a tracked 13F filer owns may be routed into a bucket, and a landing zone for between-quarter signals.

**What was built:**
- **`scripts/build_cusip_map.py`** — offline CUSIP→ticker bootstrap for the 13F universe. Resolution order: CUSIP seeds (raw pull + `ticker-map.json`) → curated issuer-name alias table → exact normalised name vs `ticker-directory.json` → 13F-abbreviation expansion (AMER→AMERICA, MATLS→MATERIALS…). Tries every issuer name ever filed for a CUSIP (the same CUSIP is spelled differently across quarters). Writes `reference-data/cusip-map.json` (1,979 of 3,647 CUSIPs; **99.4% of Q2-2026 dollar value resolved**, up from ~44%) and **`eligible-universe.json`** (1,306 tickers held by ≥1 of the 29 filers in 2026-Q2, with holder lists). Funds/ETFs a filer holds are eligible too; the rest are tagged `fund`. Unresolved names are listed with dollar weight for the OpenFIGI pass (Codex, Layer 2).
- **Guard rail in the app** (`index.html`): `loadEligibleUniverse()`, `eligibilityFor()`, `eligibilityChip()`, `guardrailAllows()`, `targGuardrailHtml()`. Adding a ticker to a bucket (`targAddTicker`) now checks the eligible set; a name no tracked filer owns needs a confirm + one-line reason, stored in `targetsData.overrides[ticker] = {reason, date}` (shape-guarded in `migrateTargets`; owned/plan untouched). Buy Targets shows an audit banner (`#targets-guardrail`) listing bucket names outside the rail; every Combined-table and Watchlist row carries a `✓ N` (held by N filers, hover for names) or `⚠ not held` / `⚠ override` chip. **Dry powder is exempt** (cash management, not a stock pick).
- **📡 Feed tab** (Super Investors group): reads `signals/feed-latest.json` per the handoff §6 contract (kind / direction / severity / investor / ticker / quote / source). Filters by kind and ticker-or-investor, stats bar (signals, touching my buckets, from filings, act-now), day grouping, bucket names highlighted. Ships with an empty placeholder file and an explanatory empty state. Rule stated on the tab: words raise a watch flag, only filings move a score.
- `APP_BUILD` → `2026-09-02a`.

**Findings surfaced by the rail on Joe's current buckets:** all 61 stock-bucket names are held by a tracked filer except **CODI** (Compass Diversified — no filer owns it). SMH and NLR are held (VanEck ETFs via Greenblatt et al.).

**Verification steps run:**
- `node --check` on the embedded JS (2 blocks) — OK
- Headless Chromium render against a local static server: guard-rail banner rendered ("2 of 61…" before the SMH alias fix, CODI after), Feed tab button + empty state rendered, 102 ✓ chips / 13 ⚠ chips, `APP_BUILD` present
- `python3 scripts/build_cusip_map.py` coverage report (see above)

**Known issues / next work:**
- `eligible-universe.json` and `cusip-map.json` are a one-off bootstrap; wire `build_cusip_map.py` into `update-13f-tracker.yml` after the holdings rebuild so they refresh each quarter (Codex lane; then replace/extend with OpenFIGI).
- Eligibility is "held by ≥1 of the 29". The conviction score / approved-universe expansion (Layers 1–2) is still to come.
- Feed is a shell until the Layer 3 collector writes real items.

---

## Session 9 — June 16, 2026
**Goal:** Extend drag-and-drop to the MOSE bucket, and add edge auto-scroll so far-apart sections can be reached.

**What was built:**
- **MOSE is now a drag participant** (`tbody data-targ-bucket="mose"` with handle rows). Reorder within MOSE, or drag a MOSE name onto an IRA bucket (and vice-versa) — works across the two separate tables via `elementFromPoint`.
- **Cross-pool owned migration:** moving a stock across the IRA↔MOSE boundary carries its owned $ to the destination's account key (`his/hers` ⇄ `mose`) so nothing is silently orphaned; same-pool moves leave owned untouched. Generalized `targDropTicker` via a `targListFor(id)` helper that resolves `'mose'` or any IRA bucket.
- **Edge auto-scroll during drag:** when the pointer nears the top/bottom of the viewport, the page scrolls (with the ghost + drop indicator tracking), so you can drag a MOSE name at the bottom up to an IRA bucket — essential on the phone.

**Verification steps run:**
- node --check; unit tests: AAPL MOSE→Forever (MOSE re-spreads to 9 @ $26,756, AAPL Forever target $103,500), WMT For Now→MOSE with owned migration ($16,946+$3,389 → mose|WMT $20,335, his/hers cleared), reorder within MOSE
- Headless Chromium: cross-table drag on a tall viewport (AAPL MOSE→Forever) AND on a short viewport relying on auto-scroll — both moved the row, no page errors

**Deploy:** merged to main and published to gh-pages (live).

---

## Session 8 — June 16, 2026
**Goal:** Drag-and-drop in the Buy Targets Combined table — reorder stocks and move them between buckets with automatic recalculation.

**What was built:**
- **Drag-and-drop on the Combined IRA table:** each row has a ⠿ handle. Drag to reorder within a bucket, or drop onto another bucket (or one of its rows) to move the stock there. Buckets are now separate `<tbody data-targ-bucket>` drop zones; rows carry `data-targ-ticker`.
- **Pointer-event implementation** (pointerdown/move/up + `touch-action:none`) so it works on both the Mac (mouse) and the iPhone (touch) — native HTML5 DnD would have been dead on iOS. Floating ghost label, drop-line indicator between rows, and bucket-highlight when hovering an empty area.
- **Automatic recalc:** moving a ticker just edits `bucket.tickers`, so equal-weight (and the dollar goals) re-spread instantly across both IRAs, MOSE untouched. Moving a stock out of a bucket drops its custom weight from that bucket (remaining names renormalize to 100%); the stock takes a default weight in its new bucket. Owned values follow the ticker. Toast confirms cross-bucket moves.

**Verification steps run:**
- Embedded JavaScript syntax check (node --check)
- Node unit tests: move MELI For Now→Forever (Forever→5 names @ $103,500, For Now→14 @ $16,429), reorder within a bucket, and weight renormalization after a weighted stock leaves (sum stays 100%)
- Headless Chromium pointer-drag test: dragged MELI's handle onto Forever — row moved buckets, combined goal recomputed to $103,500, For Now lost it, no page errors

**Deploy:** merged to main and published to gh-pages (live).

---

## Session 7 — June 15, 2026
**Goal:** Four Buy-Targets upgrades Joe greenlit, plus load his wife's IRA positions.

**What was built:**
- **Custom per-stock weights within a bucket** — new editable "% of Bucket" column in the Combined table. Setting one stock's % rebalances the others proportionally so the bucket always sums to 100% and its dollar goal stays exact. "Reset to equal" link per bucket. Single-ticker buckets (S&P/VOO) show a fixed 100%. Weights flow through to his/hers/combined and the CSV.
- **"Buy More" in shares** — every order amount now shows `≈ N sh` at the live price in the his/hers/MOSE tables, and a "Buy More (sh)" column in the CSV.
- **One-paste IBKR import** — collapsible "📥 Update from IBKR" panel: pick account, paste positions (`TICKER VALUE` or `TICKER SHARES PRICE`), Preview, Import. Forgiving parser ignores USD/Cash lines and handles $/comma formatting. Lands straight in the synced state (solves the Firebase-override problem for monthly updates).
- **Progress history** — dated snapshots auto-captured on every import (plus a manual "Save snapshot now" button). Shows a sparkline of % of IRA goal deployed over time and a table with deployed $, %, MOSE deployed, and Δ since the prior snapshot.
- **Wife's IRA loaded** from her IBKR screenshot (acct U25767390): AMZN $2,624, GOOGL $3,970, WMT $3,389 (~$190k still in SGOV/cash). Her side of the tracker is now live; combined IRA deployed = $56,901 (4.9%).
- Bumped targets data to version 2 with a load-time normalizer (adds `weights`/`history` to any older saved state).

**Verification steps run:**
- Embedded JavaScript syntax check (node --check)
- Node tests: weight rebalance (GOOGL→40% of Forever makes others 20% each, sum 100, targets recompute to $207k combined / $171k his); import parser (both formats, USD/Cash ignored); import-into-account + same-day snapshot dedup; wife data load
- Headless Chromium render of the full upgraded tab — % of Bucket column, share hints, import panel, populated Her IRA, history, outside-plan (PLD); no page errors

**Known issues / next work:**
- Import overwrites listed tickers but doesn't zero a position that was fully sold — edit that cell to 0 if needed.
- Still on the dev branch; not deployed live (holding per Joe until he gives the go-ahead).

---

## Session 6 — June 13, 2026
**Goal:** Replace the "decide the timing for me" model with what Joe actually wants — a fixed per-stock dollar-goal tracker he reverts to, updated from IBKR position screenshots.

**What was built:**
- New **🎯 Buy Targets** tab — a goal tracker, not a timing engine. Each stock has a fixed dollar target decided today; Joe buys on his own schedule and the sheet shows how much of each he still needs.
- **Two pools, kept separate:**
  - **IRA — $1.15M combined** (his $950k + wife's $200k), tracked as one goal but executed per-account. Buckets: Forever 45% / S&P 35% (VOO) / For Now 20%, equal-weight within each bucket. His/hers are mirrors scaled to each account's total.
  - **MOSE — $344k joint cash** (the former "Innovation" names), 70% to stocks ($240,800 split equally across 10 names) / 30% cash held back ($103,200). 100% separate from IRA totals.
- Three views: **Combined IRA goal progress** (per stock, his+hers), **Your IRA** and **Her IRA** execution tables with editable Owned + "Buy More" order sizes, and the **MOSE** table. Plus a **Holdings outside the plan** section for tickers held but not in any bucket.
- **Owned seeded from Joe's IBKR screenshot (acct U25747451):** GOOGL $18,044, AMZN $11,928, WMT $16,946, PLD $5,652 (flagged outside-plan). Wife's side left pending her screenshot.
- **CSV export** button (account/bucket/ticker/target/owned/buy-more/%). Bucket names renamed to Joe's labels (Forever / S&P / For Now / MOSE).
- All goals/pools/%s editable in-UI; state persists to localStorage and syncs via the shared Firebase blob (`targets` key). Cockpit/Re-Entry tabs untouched.

**Verification steps run:**
- Embedded JavaScript syntax check (node --check)
- Node unit test of target math (his Forever $106,875, S&P $332,500, For Now $12,667; hers Forever $22,500; his deployed $46,918; MOSE $240,800/$103,200) and CSV export
- Headless Chromium render of the full tab — tables, his/hers split, MOSE, outside-plan (PLD), WMT over-target flag all correct; no page errors

**Known issues / next work:**
- Wife's IRA Owned column is zero pending her positions screenshot (Joe is merging her accounts under one IBKR login / LTA).
- Updating Owned from a screenshot is currently manual entry (or I edit the seed); fine until the IBKR API is connected.
## Session 11 — June 16, 2026
**Goal:** Fix "Add Stock" search — it only matched the ~90 names MOSE already tracked, so listed companies (and private ones like Cursor/Cerebras) couldn't be found.

**What was built:**
- `reference-data/ticker-directory.json` — a NYSE/NASDAQ/AMEX symbol directory the search reads. Seeded now (~180 names from repo data + curated large/mid caps) and refreshed to the full ~10k SEC/Nasdaq listing by `scripts/build_ticker_directory.py`, wired into the weekly 13F workflow.
- Watchlist search now merges tracked names (with bucket/source hints) and the full directory; tracked entries win on collisions. Name-only adds work (the old code silently refused them).
- Pre-IPO / private add path: any typed name can be added as an unlisted company (🔒, no quote attempted). Cursor (private) is handled this way. Quote script skips `private` entries.
- Non-US listings: a curated supplement (Constellation Software CSU→CSU.TO, Cerebras CBRS, Couche-Tard ATD.TO, major ADRs) is merged into the directory, since SEC data is US-only. Foreign tickers carry a Yahoo quote symbol (`y`) so they quote correctly (e.g. CSU is fetched as CSU.TO).

**Owner action:** trigger the "Update 13F tracker" workflow once to replace the seed with the full SEC directory (the sandbox can't reach SEC/Nasdaq hosts).

---

## Session 5 — June 12, 2026
**Goal:** Give Joe a mechanical market re-entry playbook after the April 2026 Truist→IBKR move, so the monthly buys happen like clockwork regardless of where the market is.

**What was built:**
- New **📅 Re-Entry Plan** tab with two plans:
  - **IRA (IBKR) — 18-month tranche DCA**: remaining cash ÷ remaining months = base tranche; a drawdown ladder scales the order up (−5% → 1.5×, −10% → 2×, −15% → 2.5×, −20% → 3×). Each month's order is split across Watchlist buckets (Core 50 / Opportunistic 30 / Innovation 10 / Treasury 10 by default) with live tickers from those buckets shown on the buy ticket.
  - **Joint Taxable ($344k) — opportunistic dip buyer**: holds cash until cumulative dip tiers trigger (−5% deploy 15%, −10% +25%, −15% +30%, −20% +30%), with the shopping list pulled live from the Watchlist buckets.
- Drawdown is measured on the S&P 500 from a **ratcheting reference high** (auto-updates on new highs, manually overridable), plus a vs-April-exit readout (6591.90).
- Big "buy ticket" cards show this month's exact dollar order and status (⏳ waiting / 🔔 BUY NOW / ✅ done), an 18-row schedule table, the active ladder rung highlighted, and a progress bar of deployed vs dry powder.
- **Purchase log**: after placing an order at IBKR, Joe logs date/account/ticker/amount; remaining tranches recalculate, so skipped or partial months roll forward automatically.
- Command Center now shows a Re-Entry banner card (next action for both accounts) that jumps to the tab.
- All plan settings (totals, months, start, buy day, allocations, ladder multipliers, tier percentages) are editable in the UI; state persists to localStorage and syncs through the existing Firebase pipe (`reentry` key in the shared state blob).

**Verification steps run:**
- Embedded JavaScript syntax check for `index.html` (node --check)
- Node smoke tests of the tranche math (at-high 1× $50k, −11% → 2× $100k; joint tiers trigger $137.6k at −11%; purchases roll the remainder forward)
- Headless Chromium render of the cockpit banner and the full Re-Entry tab — no console errors

**Known issues / next work:**
- Live S&P quote currently comes from `indices-latest.json` / the Stooq job; per-ticker monthly-dip signals need price history (Stooq API key) before "GOOGL is down X% this month" alerts can be added.
- IBKR API hookup still pending — purchases are logged manually for now by design.
---

## Session 10 — June 12, 2026
**Goal:** Fix the dead quote pipeline, lock down exposed personal data, make watchlist buckets user-editable, and version the deep dives.

**Diagnosis:** Stooq's keyless CSV endpoint started returning empty data June 5 and hard-404s since June 9; every scheduled run failed and the published snapshot had zero quotes. The old script also computed "change %" vs the day's open rather than the previous close, and silently committed empty data as success.

**What was built:**
- `scripts/update_live_market_data.py` rewritten against Yahoo Finance's v8 chart endpoint (no API key): previous-close change %, 52-week range from quote metadata, ~daily 1Y history refresh, custom Firebase-watchlist tickers included, exit anchors moved to `reference-data/exit-baseline.json`.
- Failure policy: never overwrite good data with bad. On failure the script writes `pipeline-status.json` and exits non-zero; the dashboard shows a site-wide red/amber banner when quotes are stale, empty, or the pipeline reports an error.
- Security: Truist account numbers removed from `joes-holdings.json` and the holdings UI; dashboard password stored as SHA-256 hash instead of plaintext. Remaining owner steps documented in `docs/SECURITY-LOCKDOWN.md` (history purge, private repo, Firebase rules, password rotation).
- Watchlist buckets are now user-defined: create, rename, delete, and reorder (▲/▼) from the grouped view; definitions sync via Firebase with the rest of the state.
- Deep dives are versioned: `research-library.json` may hold multiple reports per ticker; the library shows the latest with an expandable history timeline and deltas (intrinsic value, verdict, convergence score). Per-ticker monthly/quarterly refresh cadence resurfaces due tickers in the Needs Deep Dive lane. Protocol in `docs/DEEP-DIVES.md`.
- Removed the permanently disabled GitHub Contents-API sync layer from `index.html`.

---

## Session 4 — May 11, 2026
**Goal:** Improve Watchlist sorting/grouping and add the first Research module without making Joe enter the same stock twice.

**What was built:**
- Restored the cleaner original MOSE platform UI as the base: top market bar, command center, Joe's Watchlist, Joe's Holdings, Super Investors, and Deep-Dive Research Library.
- Watchlist now has Flat mode and Group mode while keeping the original bucket-based layout.
- Flat mode can sort by priority, score, ticker, date added, margin of safety, Joe holdings first, or needs-deep-dive first.
- Group mode can group by bucket, status, conviction, portfolio role, or investor overlap.
- Watchlist rows now include manual priority, convergence score, research status, and buttons to flag/approve/dismiss deep dives.
- The existing Research Library tab now includes a Research Queue lane above completed reports.
- Research pulls from the same ticker universe as Watchlist plus auto-flagged high-convergence names, so stocks do not need to be added twice.
- Added `research_items` and `research_reports` tables to both SQLite and Supabase schemas for the future persisted version.
- Added `scripts/build_legacy_platform_data.py` to generate the root JSON files expected by the original MOSE platform UI from the current convergence master.

**Current behavior:**
- Watchlist and Research state persist in browser `localStorage`.
- Auto deep dive flags are generated from the purchase-readiness score in the original command center.
- Deep-dive requests flow into the Research Queue and also remain visible from the Watchlist/Command Center.
- Completed reports continue to live in the Research Library.

---

## Session 1 — May 7, 2026
**Goal:** Build the full MOSE dashboard as a live GitHub Pages site with all 22 Tier 1 investors, real-time stock prices, watchlist management, and convergence scoring.

**Reference data available:**
- `reference-data/convergence-master.json` — 11 investors already pulled, 263 unique stocks, top 30 convergence rankings
- `reference-data/convergence-summary.md` — human-readable summary
- `reference-data/MOSE-DATA-PROTOCOL.md` — full data protocol and investor list
- `reference-data/MOSE.md` — full product spec

**Architecture decided:** Single-file HTML dashboard (no build tools, no npm, vanilla JS/CSS). Pulls live stock prices from Yahoo Finance unofficial API. Data stored in embedded JSON updated by a companion Python script.

**Status:** Completed initial single-file build

---

## Session 2 — May 7, 2026
**Goal:** Produce the hosted GitHub Pages dashboard files requested in `CODEX-PROMPT.md`.

**What was built:**
- `index.html` — single-file vanilla HTML/CSS/JS dashboard with six tabs, dark MOSE styling, mobile-responsive layouts, localStorage watchlist, live Yahoo Finance price hooks, source labels, stale-data warnings, and safe placeholder states.
- `pull_13f.py` — conservative SEC EDGAR refresh script that uses the SEC full-text search endpoint, parses 13F information tables when a verified CIK map is supplied, backs up the old convergence file, and refuses to fabricate missing data.
- `deploy.sh` — GitHub Pages deploy script using the requested `git subtree split --prefix . main` flow.

**Tab-by-tab status:**
- Convergence Score — working from `reference-data/convergence-master.json`; live price cells fetch Yahoo Finance when the page is served over HTTP.
- Investor Profiles — working for all protocol investors; loaded investors show real filing data, unloaded investors show `13F Not Yet Loaded`.
- My Watchlist — working with add/remove, notes, holding badges, and `localStorage`; Yahoo quoteSummary is used for 52-week range and P/E when available.
- Signals — partially working; consensus and high-conviction monitor items are derived from loaded data. Add/trim/exit/new-position signals are explicitly marked unavailable because historical trend fields are not present in the current JSON.
- Data Status — working for the 22 Tier 1 protocol investors with freshness based on real filing dates and the May 15, 2026 deadline.
- Portfolio Tracker — working as a source-labeled tracker for Joe's nine known holdings. Gain/loss remains unavailable because March/April 2026 execution prices are not present in the repo data.

**Architecture decisions:**
- No build tools, npm packages, or frameworks were added.
- The dashboard fetches `./reference-data/convergence-master.json` at startup, so it should be served over HTTP rather than opened directly from disk.
- The app treats the current JSON schema as authoritative. It handles the actual `investors` array and numeric `investors_pulled` / `investors_failed` fields present in the file.
- No placeholder investment positions or entry prices were invented.

**Known issues:**
- Yahoo Finance unofficial endpoints may block browser requests from some origins or rate-limit bursts; failed cells remain visibly unavailable rather than being shown as current.
- The SEC refresh script requires a user-maintained `reference-data/cik-map.json` before it can safely identify each manager's CIK. Because raw 13F XML does not reliably include tickers, `reference-data/ticker-map.json` is also needed for clean ticker output; otherwise unresolved holdings are labeled by CUSIP.
- Current convergence data contains some issuer-name strings where ticker symbols should be, inherited from the existing JSON.

**Verification steps:**
- Validate JavaScript syntax by loading `index.html` in a browser or serving locally with `python3 -m http.server 8000`.
- Validate Python syntax with `python3 -m py_compile pull_13f.py`.
- Confirm dashboard data loading at `http://localhost:8000/`.

**How to deploy:**
- Run `chmod +x deploy.sh` once if needed.
- Run `./deploy.sh` from the repository root.
- Live URL: `https://roblobsterclaw.github.io/mose/`

---

## Session 3 — May 7, 2026
**Goal:** Move MOSE toward a stronger, more accurate, live architecture without overbuilding the cloud layer too early.

**Decision:** Use SQLite first as the canonical local truth store, then migrate to Supabase/Postgres after the schema is proven and MOSE needs always-on hosted jobs, auth, multi-device state, or a hosted API.

**What was built:**
- `db/schema.sql` — local SQLite schema for investors, filings, securities, holdings, convergence rankings, price snapshots, Joe's portfolio lots, signals, source events, and export runs.
- `scripts/mose_db.py` — CLI for initializing the database, importing the current convergence JSON, exporting dashboard JSON, and checking DB status.
- `scripts/build_dashboard_data.sh` — one-command pipeline that initializes SQLite, imports the current snapshot, exports `reference-data/convergence-master.json`, and prints counts.
- `supabase/migrations/001_initial_truth_store.sql` — Supabase/Postgres migration mirroring the SQLite schema for the later hosted phase.
- `adapters/brokerage.py` — read-only brokerage adapter contract for accounts, positions, and recent trades.
- `adapters/ibkr.py` — read-only IBKR placeholder for future TWS API / IB Gateway or Client Portal Web API integration.
- `docs/ARCHITECTURE.md` — phase-by-phase architecture note.
- `.gitignore` — excludes local DB files and Python caches.

**Phase status:**
- Phase 1, SQLite truth store — working locally. Current data imported into `data/mose.db`.
- Phase 2, dashboard JSON export — working. The dashboard still reads static JSON, but that JSON is now an export artifact.
- Phase 3, Supabase path — scaffolded with a migration; not applied to Supabase yet.
- Phase 4, IBKR path — scaffolded read-only; no account connection or trading logic added.

**Verification steps run:**
- `bash scripts/build_dashboard_data.sh`
- `python3 scripts/mose_db.py status`
- `python3 -m py_compile scripts/mose_db.py pull_13f.py adapters/brokerage.py adapters/ibkr.py`
- Embedded JavaScript syntax check for `index.html`

**Current DB counts after import:**
- Investors: 11
- Filings: 11
- Securities: 264
- Holdings: 102
- Rankings: 263
- Portfolio lots: 0
- Signals: 0

**Known issues / next work:**
- `reference-data/cik-map.json` and `reference-data/ticker-map.json` are still required before the 13F puller can safely refresh all Tier 1 investors.
- Holdings imported from the current snapshot are top-10 only. Full 13F history still needs to be pulled and stored quarter-by-quarter.
- Joe's actual portfolio lots are not loaded yet, so portfolio value and gain/loss are not authoritative.
- Browser-side Yahoo Finance remains fragile and should be replaced by a backend price snapshot job.

---
