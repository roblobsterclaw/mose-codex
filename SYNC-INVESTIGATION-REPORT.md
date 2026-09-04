# MOSE Dashboard — Cross-Device Sync Investigation

> Historical production-MOSE report. In this independent Codex copy, the three
> generic migrations described below are archived under
> `docs/legacy-supabase-migrations/` and cannot run through the active migration
> path. Only `mose_codex_*` tables are active in this copy's migration.

**Date:** 2026-06-12
**Investigator:** Claude (for Joe Lynch)
**Repo:** `roblobsterclaw/mose` → https://roblobsterclaw.github.io/mose/
**Local path:** `/Users/joemac/Documents/Codex CLI Projects/mission-control-dashboard/Codex 1/MOSE DASHBOARD`

---

## TL;DR (the one-paragraph answer)

Every change Joe makes on the dashboard — watchlist buckets, notes, priorities, custom
tickers, research status, deep-dive requests — is saved **only to that one browser's
`localStorage`**. `localStorage` is private to a single browser on a single device, so
nothing he does on his iPhone is ever visible on the Mac Mini, and vice versa. The
dashboard *does* contain a complete GitHub-API sync system that was meant to fix exactly
this — but it is **permanently disabled**: the function that supplies the GitHub token,
`getGithubToken()`, simply does `return ''`, and it has returned an empty string in
**every commit of the current dashboard's history**. With no token, every save/load-to-
cloud path short-circuits on its first line and falls back to `localStorage`. The Supabase
backend that exists in the repo is wired up for the **13F super-investor data only** (via a
nightly GitHub Action) and is **never touched by the dashboard front-end**. There is **no
divergent/unmerged copy** of `index.html` — the two Codex sessions both committed to this
same repo's `main` branch. **Recommended fix: copy the proven Firebase Realtime Database
pattern from Joe's JFL TTD dashboard** (lowest effort, already proven, public-safe).

---

## 1. CURRENT STATE — What syncs and what doesn't

The dashboard is a single self-contained `index.html` (4,263 lines) served as a static page
from GitHub Pages. It pulls data four different ways:

### a. Static JSON fetched from the repo (READ-ONLY, syncs to everyone)
These files are committed to the repo and refreshed by GitHub Actions. Every device sees the
same data because they're just downloading the same files. **These already "sync."**

| File | Loaded by | Refreshed by |
|------|-----------|--------------|
| `indices-latest.json` | `loadIndices()` (5-min auto-refresh) | `update-live-market-data.yml` |
| `live-quotes.json` | `loadIndices()` | `update-live-market-data.yml` |
| `holdings-latest.json` | `loadHoldings()` | (build scripts) |
| `dcf-latest.json` | `loadDCF()` | (build scripts) |
| `filing-changes-latest.json` | `loadFilingTracker()` | `update-13f-tracker.yml` |
| `joes-holdings.json` | `loadJoeHoldings()` | manual |
| `research-library.json` | `loadResearchLibrary()` | manual |
| `symbol-snapshots.json` | `loadSymbolData()` | `update-live-market-data.yml` |
| `price-history.json` | `loadSymbolData()` | `update-live-market-data.yml` |
| `investors.json` | `renderInvestors()` | manual |

> Note: market data **does** appear current on all devices — that's why Joe sees fresh
> quotes everywhere. That part was never broken. The broken part is **his personal edits.**

### b. localStorage (USER-EDITABLE, per-device, NEVER synced) — **THE PROBLEM**
All of Joe's personal, hand-entered data lives here. `localStorage` is scoped to one origin
*in one browser profile on one device*. Safari-on-iPhone and Chrome-on-Mac do not share it,
period. The keys (confirmed in `index.html`):

| localStorage key | What it holds | Where written |
|------------------|---------------|---------------|
| `mose_watchlist_buckets_local` | Bucket assignment per ticker (Core Forever, etc.) | `saveWatchlistLocalState()`, `onBucketChange()` |
| `mose_watchlist_notes_local` | Free-text notes per ticker | `updateWatchlistNote()` |
| `mose_watchlist_priority` | High/Medium/Low/None per ticker | `setPriority()` |
| `mose_custom_watchlist` | Tickers Joe added by hand | `saveWatchlistLocalState()` |
| `mose_research_items` | Research status/notes per ticker | `saveResearchItems()` |
| `mose_dd_requests_local` | Deep-dive request checkboxes | `toggleDDRequest()`, `requestDDUpdate()` |
| `mose_watchlist_view` / `_sort` / `_group` | UI view preferences | `setWatchlistView/Sort/Group()` |
| `mose_theme` | Light/dark toggle | `toggleTheme()` |

Initial load reads these at lines 1884–1892. The autosave hub is `saveWatchlistLocalState()`
(line 2669), which writes **six** of these keys on every edit — to `localStorage` only.

### c. GitHub-API based (BUILT but DISABLED — currently dead code)
The dashboard contains a full read/write sync layer against the GitHub Contents API,
targeting three files under `data/`:

- `loadDDRequestsFromGitHub()` / `saveDDRequestsToGitHub()` → `data/deep-dive-requests.json`
- `loadWatchlistBuckets()` / `saveWatchlistBucketsToGitHub()` → `data/watchlist-buckets.json`
- `loadWatchlistNotes()` / `saveWatchlistNotesToGitHub()` → `data/watchlist-notes.json`
- `syncAllToGitHub()` → all three at once

These **are called on startup** (lines 4196–4198 and 4217–4219) and on hard-refresh. **But
they all immediately bail**, because every one of them begins with:

```js
const token = getGithubToken();
if (!token) { /* render local data and */ return; }
```

…and `getGithubToken()` is hardcoded to fail:

```js
function getGithubToken() {
  return '';            // index.html line 1880–1882
}
```

`promptGithubToken()` likewise no longer prompts — it just shows the toast
*"Public site is view-only."* (line 2745). So the GitHub layer is present but **inert**.

> **Why it was disabled (and why we should NOT just re-enable it):** writing to GitHub
> requires a Personal Access Token with **write** scope. On a *public* GitHub Pages site,
> any embedded token is trivially visible in "View Source" and would let anyone push to the
> repo. Hardcoding `return ''` was the correct security decision — it was deliberately
> neutered when the app became a public, password-gated static site.

The `data/*.json` files in the repo are therefore **stale April/May seed data** (the bucket
file has only 10 tickers, notes file has 1 entry) — they have not been updated by the
front-end because the front-end can't write to them.

### d. Never connected (Supabase backend exists but the dashboard ignores it)
See §4. The Supabase project is real and populated by a server-side Action for 13F data, but
`index.html` contains **zero** references to Supabase (only one comment, line 1367). The
front-end never reads or writes Supabase.

### Authentication note
Access is gated by a **client-side hardcoded password** (`'soccer12'`, line 1020) stored in
`sessionStorage` as `mose_auth`. This is cosmetic, not real security — the password is in the
page source. Worth knowing because any "real" sync backend should not rely on it.

---

## 2. THE PROBLEM — Why iPhone ≠ Mac, data type by data type

| Data | Storage | Syncs across devices? | Why / Why not |
|------|---------|----------------------|---------------|
| Live quotes, indices, holdings, DCF, 13F changes, charts | Static JSON in repo | ✅ **Yes** | Same file downloaded by every device; refreshed by Actions |
| Watchlist bucket assignments | `localStorage` | ❌ **No** | Per-browser; GitHub save path dead (no token) |
| Watchlist notes | `localStorage` | ❌ **No** | Same |
| Priorities (High/Med/Low) | `localStorage` | ❌ **No** | Same |
| Custom-added tickers | `localStorage` | ❌ **No** | Same |
| Research status/notes | `localStorage` | ❌ **No** | Same |
| Deep-dive request checkboxes | `localStorage` | ❌ **No** | GitHub save path dead (no token) |
| View/sort/group/theme prefs | `localStorage` | ❌ **No** (and shouldn't need to) | Device-local prefs |

**Plain-English version for Joe:** The dashboard treats every browser as its own private
notebook. When you tap a bucket on your iPhone, the iPhone writes it into the iPhone's own
notebook. The Mac has a *different* notebook and never hears about the change. The app was
supposed to also copy changes up to GitHub so all devices share one notebook, but that
feature was turned off (for a good security reason) and never replaced with a safe one.

---

## 3. PARALLEL WORK RISK — Did the two Codex sessions cause divergence?

**No divergence. No risk.** Findings:

- The referenced path `/Users/joemac/Documents/Codex/MOSE DASHBOARD/` **does not exist** on
  this machine. A filesystem search found only this repo and an adjacent unrelated
  `…/Codex 1/MOSE PROJECT/` folder. No second working copy of the dashboard exists.
- The git repo has only two branches — `main` (checked out) and `gh-pages` (the deploy
  target). No stray feature branches, no unmerged work.
- `index.html`'s history is a single linear chain. The light-/text-contrast work attributed
  to the second Codex session is committed **right here in `main`**:
  - `7bce82f Improve light mode contrast`
  - `bf6a983 Add light/dark theme toggle`
  - `b6b0737 Improve MOSE dashboard text contrast`
  - `7fd2baf MOSE Dashboard update 2026-05-14 20:50`
- Both Codex sessions ultimately landed in this same repo. The "wrong path" the second
  session referenced was just a stale/aliased working directory note; the commits prove the
  edits reached the canonical repo.

So there is **no orphaned, divergent index.html** to merge or recover. The single source of
truth is intact. (Confirmed: `getGithubToken()` returns `''` in *every* historical version
of `index.html` — the sync was never live in the deployed app, in any session.)

---

## 4. BACKEND STATUS — What exists vs. what's wired up

### What EXISTS (infrastructure)
- **SQLite truth-store**: `db/schema.sql`, `data/mose.db` (272 KB), driven by
  `scripts/mose_db.py` (full import/export CLI).
- **Supabase project**: `https://simbfvtcnjhpzuvfmvop.supabase.co` with a service-role key.
  Three migrations under `supabase/migrations/`:
  - `001_initial_truth_store.sql` — 20+ tables: `investors`, `filings`, `securities`,
    `holdings`, `convergence_rankings`, `holding_changes`, `price_snapshots`,
    `price_history`, `symbol_metrics`, `portfolio_lots`, **`research_items`**,
    `research_reports`, etc.
  - `002_symbol_snapshots.sql` — symbol snapshot / metrics tables.
  - `003_13f_tracker.sql` — quarter-over-quarter 13F change tracking.
- **Server-side sync**: `scripts/sync_13f_tracker_to_supabase.py`, invoked by
  `.github/workflows/update-13f-tracker.yml` (nightly, using `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` repo secrets).
- **Brokerage adapters**: `adapters/brokerage.py` (read-only `Protocol` contracts:
  `BrokerageAccount`, `BrokeragePosition`, `BrokerageTrade`) and `adapters/ibkr.py`
  (`IBKRReadOnlyAdapter` — **all methods raise `NotImplementedError`**, explicitly a
  placeholder; no live brokerage connection exists).

### What is actually WIRED UP
- Supabase receives **13F tracker data only**, written **server-side** by the nightly
  Action with the **service-role** key.
- The Supabase schema *has* a `research_items` table — but the dashboard's research data
  goes to `localStorage` (`mose_research_items`), **not** to that table. The schema and the
  front-end were never connected.

### The gap
- **The browser never talks to Supabase.** No Supabase JS SDK, no anon key, no REST calls in
  `index.html`. The service-role key (which exists) must **never** be embedded in the public
  page — it's all-powerful. So Supabase as-is cannot be reached from Joe's devices without
  new front-end code + a safe (anon) key + Row-Level-Security policies.
- There is **no table** modeling the dashboard's simple per-ticker key-value edits (buckets,
  notes, priority, custom tickers, DD checkboxes) as a single user's preferences. The schema
  is built for the multi-investor 13F truth-store, not lightweight personal app-state.

---

## 5. RECOMMENDED FIX — Make ALL user data sync, ranked by effort × reliability

The goal: a backend the **public, password-gated static page** can both **read and write**
from any device, **without embedding any high-privilege secret**. All three options below
satisfy "no exposed write-secret" *except* the GitHub one — which is why GitHub ranks last.

### 🥇 Option B — Firebase Realtime Database (RECOMMENDED)
Copy the **exact pattern already proven in Joe's JFL TTD Dashboard** (Firebase Realtime DB,
SDK v5.94).

- **Effort:** **Lowest.** The pattern is already working in another of Joe's apps, so the
  builder knows it cold. Add the Firebase SDK `<script>`, paste a config block, and replace
  (or mirror) the ~6 `localStorage.setItem` calls in `saveWatchlistLocalState()` with a
  single `db.ref('mose/<user>').set(state)`, plus one `.on('value', …)` listener that
  rehydrates the UI when any device changes the data. Real-time, instant, no save button.
- **Reliability:** **Highest** for this use case — it's literally built for "one JSON tree,
  many devices, live." Already battle-tested in TTD.
- **Security:** The Firebase web config (apiKey, etc.) is **designed to be public** — it's an
  identifier, not a secret. Lock writes with Realtime-DB security rules (e.g. require Firebase
  **Anonymous Auth**, or a shared rule). Far safer than a GitHub write-token.
- **Migration:** On first load, seed the DB from existing `localStorage` so Joe doesn't lose
  current edits; thereafter DB is the source of truth and `localStorage` becomes just a cache.
- **Cost:** Free tier is ample for one user's preference blob.

### 🥈 Option A — Wire up the existing Supabase
- **Effort:** **Medium.** Infra partly exists, but you'd need to: (1) add a new table for the
  dashboard's KV app-state (e.g. `user_app_state(user_id text, key text, value jsonb)` — the
  current schema doesn't have one), (2) enable **Row Level Security** + a policy keyed to the
  **anon** key, (3) add the Supabase JS client (or REST `fetch`) to `index.html` and swap the
  `localStorage` writes for `upsert`/`select`, plus a Realtime subscription for live updates.
- **Reliability:** High once configured; Supabase Realtime is solid.
- **Security:** Use the **anon** (public) key in the browser — safe by design — gated by RLS.
  **Never** the service-role key. The existing service-role key stays server-side for the
  13F Action only.
- **Why second:** More moving parts than Firebase, and it duplicates capability Joe already
  runs successfully on Firebase. Best if Joe wants ONE backend for *both* the 13F truth-store
  *and* personal edits long-term.

### 🥉 Option C — GitHub API as a lightweight backend (NOT recommended)
- **Effort:** Deceptively low — **the code already exists** (`saveWatchlistBucketsToGitHub`,
  etc.); you'd "just" make `getGithubToken()` return a real token.
- **Reliability:** Poor for this pattern — every edit is a Git commit (rate-limited, noisy
  history, race conditions on the file `sha`, slow).
- **Security:** **Disqualifying on a public site.** A write-scoped PAT in client JS is
  readable by anyone who views source; they could push to / delete the repo. Storing it in
  `localStorage` per device means Joe must paste a high-privilege token into every device,
  and it's still exfiltratable. **This is exactly why it was disabled — do not revive it.**
- **Only** defensible if the site were made private (it isn't) or moved behind a server-side
  proxy that holds the token — at which point you've built a backend anyway, so use B or A.

### Ranking summary

| Rank | Option | Effort | Reliability | Secret-safe on public site? |
|------|--------|--------|-------------|------------------------------|
| 🥇 1 | **Firebase Realtime DB** (clone TTD) | **Low** | **High** | ✅ Yes (public config + DB rules) |
| 🥈 2 | Supabase (anon key + RLS + new KV table) | Medium | High | ✅ Yes (anon key) |
| 🥉 3 | GitHub Contents API | Low-ish | Low | ❌ **No — insecure** |

---

## 6. NEXT STEPS (actionable)

**Recommended path — Firebase, mirroring TTD:**

1. **Pull the Firebase config + init pattern** from the JFL TTD Dashboard (Realtime DB
   v5.94) — same Firebase project or a new one; create a DB path like `/mose/joe`.
2. **Add the Firebase SDK** `<script>` tags + `firebase.initializeApp(config)` to
   `index.html` (config is public-safe).
3. **Set Realtime-DB security rules** — require Firebase Anonymous Auth (or a shared
   authenticated rule) so only Joe writes; deny anonymous public writes.
4. **Refactor the storage layer** so it's the single choke point:
   - On load: subscribe with `db.ref('mose/joe').on('value', snap => hydrateState(snap.val()))`.
   - On edit: change `saveWatchlistLocalState()` to write the full state object to the DB
     (keep `localStorage` as an offline cache + first-run seed).
   - This cleanly covers **all** affected keys: buckets, notes, priority, custom watchlist,
     research items, DD requests.
5. **One-time migration:** on first run after deploy, if the DB path is empty, seed it from
   the device's current `localStorage` so Joe's existing edits survive. Do this from the
   device that has the **most complete** data (likely the Mac Mini).
6. **Re-enable the deep-dive request UI** to write to the same DB instead of the dead GitHub
   path; remove or repurpose the now-obsolete `getGithubToken()` / `*ToGitHub()` functions
   to avoid confusion (they're dead code today).
7. **Test the loop:** edit a bucket on the Mac → confirm it appears on the iPhone within a
   second, and vice-versa. Verify after a hard refresh and after closing/reopening.
8. **(Optional, later)** If Joe wants a single backend, migrate the 13F/Supabase data model
   too — but that's independent of fixing personal-edit sync and shouldn't block it.

**Housekeeping regardless of option chosen:**
- Decide whether the stale `data/watchlist-buckets.json` / `-notes.json` /
  `deep-dive-requests.json` seed files should be migrated into the new backend, then stop
  treating them as a source of truth.
- Replace the cosmetic hardcoded `'soccer12'` password with real auth if the data is going
  to live in a shared cloud DB (Firebase Anonymous Auth covers the sync rules; a real login
  is a separate, optional hardening step).

---

## Appendix — Key evidence (file:line)

- `index.html:1880-1882` — `getGithubToken()` returns `''` (the master kill-switch).
- `index.html:1884-1892` — initial state read from `localStorage`.
- `index.html:2669-2679` — `saveWatchlistLocalState()`: writes 6 keys to `localStorage` only.
- `index.html:1953-2002` — DD-request GitHub load/save (both bail without token).
- `index.html:2681-2825` — watchlist bucket/notes GitHub load/save (bail without token).
- `index.html:2838-2891` — `syncAllToGitHub()` (localStorage-only fallback when no token).
- `index.html:2745-2747` — `promptGithubToken()` → "Public site is view-only".
- `index.html:4207-4226` — `DOMContentLoaded` init (calls the inert GitHub loaders).
- `index.html:1013-1031` — client-side password gate (`'soccer12'`, `mose_auth`).
- `supabase/migrations/001_initial_truth_store.sql` — full 13F/research schema (no KV table).
- `.github/workflows/update-13f-tracker.yml` — the only thing that writes Supabase
  (server-side, service-role key).
- `adapters/ibkr.py` — brokerage integration is a `NotImplementedError` placeholder.
- Git: only `main` + `gh-pages` branches; no divergent index.html; light-mode work is in
  `main` (7bce82f, bf6a983, b6b0737, 7fd2baf).
