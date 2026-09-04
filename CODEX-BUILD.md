# MOSE Codex Lab

This repository is the independent Codex implementation of MOSE.

- Repository: `https://github.com/roblobsterclaw/mose-codex`
- Intended Pages URL: `https://roblobsterclaw.github.io/mose-codex/`
- Production MOSE is separate: `https://github.com/roblobsterclaw/mose`
- Never push, deploy, or write state to the production MOSE repository or its
  `/mose` Firebase namespace from this copy.
- This copy uses the `/mose-codex` Firebase namespace until its Supabase-backed
  state store is ready.
- Accuracy over speed. Unresolved facts stay visibly unresolved.
- Read-only investment integrations only. Never stage or execute a trade.

## Data correctness rules

- Modern SEC 13F XML market values are stored in U.S. dollars, never multiplied
  by 1,000.
- Quarter comparisons match securities by CUSIP before using ticker symbols.
- Unresolved CUSIPs remain unresolved and cannot be emitted as fake tickers.
- The committed tracked history currently covers 29 approved managers. The
  independent full-filer scan now publishes a two-lane candidate pool for
  managers 30-50; every addition still requires philosophy evidence and Joe's
  written approval.
- The isolated Supabase migration is ready but not connected until this
  repository receives its own secrets.
