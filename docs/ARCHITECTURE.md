# MOSE Architecture

MOSE is moving from a static dashboard toward a reliable investment intelligence system.

## Phase 1: SQLite Truth Store

SQLite is the canonical local store for investors, filings, securities, holdings, convergence rankings, portfolio lots, signals, prices, and source events.

Primary files:
- `db/schema.sql` creates the local schema.
- `scripts/mose_db.py` initializes, imports, exports, and reports on the database.
- `data/mose.db` is the local working database and should not be committed.

## Phase 2: Static Dashboard Export

The GitHub Pages dashboard remains simple. It reads `reference-data/convergence-master.json`, but that JSON should now be treated as an export artifact, not the source of truth.

Build command:

```bash
bash scripts/build_dashboard_data.sh
```

## Live Quotes

`scripts/update_live_market_data.py` runs on a GitHub Actions schedule and
pulls quotes from Yahoo Finance's public v8 chart endpoint (Stooq's keyless
endpoint died in June 2026). Key behaviors:

- Change % is computed against the previous close (not the day's open).
- 52-week high/low come from the quote metadata; 1-year daily history is
  refreshed about once a day for the charts.
- "vs exit" anchors live in `reference-data/exit-baseline.json`.
- Custom tickers added from the dashboard UI are picked up via the synced
  Firebase state, so they get quotes too.
- The script never overwrites good data with bad: on failure it writes
  `pipeline-status.json` and exits non-zero, and the dashboard shows a
  site-wide banner when data is stale, empty, or the pipeline reports an error.

## Watchlist And Research

The dashboard now treats watchlist and research as one shared ticker universe.

- Watchlist controls are local-first, persist in `localStorage`, and sync
  across devices through Firebase Realtime DB.
- Buckets are user-defined: create, rename, delete, and reorder them from the
  grouped watchlist view (bucket definitions sync like the rest of the state).
- Flat mode sorts by priority, ticker, date added, convergence, 52-week discount, Joe holdings first, or needs deep dive first.
- Group mode groups by status, conviction, portfolio role, or investor overlap.
- Research has three lanes: Needs Deep Dive, Research Queue, and Research Library.
- Deep dives are versioned per ticker with a monthly/quarterly refresh cadence
  and period-over-period comparison — see `docs/DEEP-DIVES.md`.
- `research_items` and `research_reports` are in the database schema so this local workflow can be promoted into SQLite/Supabase storage later.

## Phase 3: Independent Supabase Store

`supabase/migrations/001_codex_investor_intelligence.sql` creates only tables
prefixed with `mose_codex_`. The inherited generic migrations are retained under
`docs/legacy-supabase-migrations/` for reference and cannot run through the
Supabase migration command. The Codex store is ready to apply after this
repository receives its own Supabase secrets.

## Phase 4: IBKR Later

Brokerage integration starts read-only. The adapter contract in `adapters/brokerage.py` supports accounts, positions, and trades. `adapters/ibkr.py` is a placeholder for TWS API / IB Gateway or Client Portal Web API integration after portfolio lots are stable.

No automated trading should be added until MOSE has explicit confirmations, risk limits, audit logging, and rollback procedures.
