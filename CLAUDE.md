# MOSE product context (copied into the independent Codex Lab)

> Repository boundary: this copy belongs to `roblobsterclaw/mose-codex` and
> uses the `/mose-codex` Firebase namespace. Never deploy it to, push it into,
> or write state for `roblobsterclaw/mose`. See `CODEX-BUILD.md`.

MOSE ("Margin of Safety Engine") is a static single-file stock dashboard
(`index.html`, vanilla JS/CSS, GitHub Pages). Owner: Joe (Joe Lynch / "J
lobster"). Wife: **Keli**. This file is auto-context for new sessions — read
it first.

## Deploy / workflow rules (standing)
- Develop on **`main` in `roblobsterclaw/mose-codex` only**. Deploy by triggering the **`update-live-market-data.yml`**
  GitHub Action (force-pushes `main` → `gh-pages`).
- **Never open a PR** unless Joe explicitly asks.
- Never push to other branches without permission. Don't expose the model ID in
  commits/code.
- The app syncs cross-device via its isolated Firebase namespace (`https://jfl-ttd-default-rtdb.firebaseio.com/mose-codex`),
  which is **unreachable from the sandbox** (only the GitHub Action runner can
  reach Firebase/SEC/Stooq/Nasdaq). So the app can't be driven from here — it's a
  static site; research is hand-authored and committed.

## The 8-bucket taxonomy (LOCKED — Joe approved)
One shared set of 8 buckets feeds **all three accounts** identically. Same names
everywhere: Buy Targets, Joe's Watchlist, Command Center, Re-Entry.

1. **Forever compounders** — GOOGL, AMZN, BRK.B, AAPL, MSFT, META, COST, MELI, CSU, WMT
2. **Toll booths** — V, MA, AXP, MCO, SPGI, PGR
3. **Hard assets** — BN, PLD, CP, CVX, OXY, GE, HON, NLR
4. **AI core** — AVGO, LRCX, TSM, ASML, NVDA, SMH
5. **AI bench** — COHR, CIEN, FN, CLS, MKSI, MTSI, AEIS, TTMI, VIAV, SITM, WDC, TSEM, CBRS, MU, INTC, ARM, AMD
6. **Opportunistic** — UBER, APP, MDB, DASH, RBLX, FROG, KVYO, BABA, CVNA, TSLA, SPCX, CODI, MBGL, BE
7. **Radar** (researched, circling, not yet bought) — LLY, DE, ROP, FICO, VRSN, ORLY, TXN, RACE
8. **Dry powder** — VOO, VTV, QQQ, IDGT, SGOV

Bucket %s (starting points, editable in ⚙️ Edit goals): Forever 35 / Toll 10 /
Hard 10 / AI core 8 / AI bench 4 / Opp 8 / Radar 5 / Dry powder 20 (=100).

## The account model (implemented in the Buy Targets page, v7 data)
- Three accounts, all sharing the 8 buckets: **Joe's IRA** ($950k, key `his`),
  **Keli's IRA** ($200k, key `hers`), **Joint Cash** ($344k, key `joint`).
- One list, "feels like one account." Each account's per-stock $ target =
  `account size × bucket% × stock's share of bucket` — an **auto proportional
  split** (Joe ~63.6% / Keli ~13.4% / Joint ~23%). Override per stock via the
  lock/% control. **No per-bucket routing** — every account gets the same names
  by default (Joe's explicit call).
- IRAs and the joint taxable account are **legally separate**; the app just lets
  him plan them as one. Data model: `targetsData.ira.accounts.{his,hers,joint}` +
  shared `targetsData.ira.buckets`; owned/plan keyed `account|ticker`. Migration
  is versioned (currently v7); preserve owned/plan on any change.

## Buy-day workflow (the core use case)
Joe decides buys on MOSE → **prints the buy list** (landscape, per-account order
sheet) → signs into each IBKR account separately and enters orders manually
(his login sees his IRA + Joint; Keli's is a separate login). The printout must
show the per-account $ breakdown. Keep it aligned to this.

## IBKR connector (Interactive Brokers)
- Connected via claude.ai Connectors → tools appear as `mcp__Interactive_Brokers_IBKR__*`.
  Flaky mid-session; a fresh session picks it up reliably after a global reconnect.
- **Joe's login exposes his IRA + Joint Cash.** Keli's IRA is a **separate login**
  and needs documented authorization from IBKR + Keli (Stage 2).

### NEXT TASK when the connector is live: create 8 IBKR watchlists (Option A)
Names = the 8 buckets above; contents = the ticker lists above. **Pull existing
watchlists first** (`get_watchlists`) and extend rather than duplicate. No
account prefixes (Joe & Keli IRAs share targets; watchlists aren't account-tied).
Ticker gotchas: `BRK.B` → **"BRK B"** on IBKR; **CSU** = Constellation Software
(Toronto/TSE, CAD; US OTC line is CNSWF); **SPCX** may now be **SPCK**; confirm
the **MBGL** (Mercedes-Benz ADR) contract. Resolve each via contract search.

### Stage 2 (parked, wanted "shortly")
Connect Keli's IRA (needs auth), then a **"tee up the trades" staging flow**: MOSE
buy list → Joe approves → agent **stages** orders in each account via
`create_order_instruction` (stage, never execute) → Joe verifies vs printout →
**Joe** submits. Hard rule: the agent never auto-executes. Guardrails + dry-run
first. Multi-account reach is the open question (separate logins).

## Research library
Deep dives are hand-authored HTML in `deep-dives/`, indexed in
`research-library.json` (versioned per ticker). ~77 reports. Write full,
GOOGL-quality reports; group the library by broad industry. Never publish broken
model numbers as fact — flag caveats.

## Known data caveats (do NOT present as fact)
- **CVNA & ROP**: the app's live price feed conflicts with the DCF reference
  price — reconcile before trusting any upside %.
- **KMX**: model IV (~$9) is not credible — judge qualitatively.
- **ASM** in the watchlist = **Avino Silver & Gold Mines** (a miner), NOT ASM
  International (that's ASMIY). Verify if a chip-tool name was intended.
- Some DCF IVs are broken (TSM/BABA ADR-FX mis-scale, TSLA auto-only). Written
  qualitatively with ⚠️ caveats.

## Interaction notes
- Joe dislikes repeated questions — lock in standing answers, act on sensible
  defaults, don't tack "want me to…?" onto every message.
- Automated snapshots are ON HOLD until Joe says go.

## Guard rail + feed (added 2 Sep 2026) — see docs/CODEX-HANDOFF-2026-09.md
- **Joe's rule:** only stocks a tracked 13F filer owns may go into a bucket. Source of
  truth: `eligible-universe.json` (built by `scripts/build_cusip_map.py` from
  `data/sec-13f-filings.json`, latest quarter). Names outside it need a logged override
  (`targetsData.overrides`). Dry powder bucket is exempt. Buy Targets shows an audit banner.
- `reference-data/cusip-map.json` = offline CUSIP→ticker bootstrap (99%+ of value). Codex's
  OpenFIGI pass should extend it, not replace the format.
- `signals/feed-latest.json` = between-quarter signal feed (📡 Feed tab). Contract in the
  handoff §6. **Words raise a watch flag; only filings move a score.**
- A second builder (ChatGPT Codex) works the pipeline side on `codex/*` branches; Claude owns
  `index.html`, research, email, this file. Log every session in `BUILD-LOG.md`.
- Sandbox network: Joe is switching the cloud environment to Full access + LunarCrush
  connector. Running sessions keep the old policy — start a fresh session for SEC-direct work.
