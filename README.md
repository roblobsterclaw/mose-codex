# MOSE Codex Lab

Independent build of Joe Lynch's Margin of Safety Engine.

This repository is intentionally separate from the existing MOSE application.
It has its own GitHub history, GitHub Pages deployment, Firebase namespace, and
Supabase table names. Work here must never deploy to or write state into
`roblobsterclaw/mose`.

## Current build focus

- Quarterly SEC bulk 13F universe screening.
- A selective, Joe-approved Top 50 super-investor roster.
- CUSIP-keyed history, concentration, patience, and turnover checks.
- Four-times-daily monitoring of approved investors' structured filings.
- Verified first-party source registry for letters, interviews, podcasts, and
  posts.
- Audited JSON exports and isolated Supabase persistence.

See `docs/SUPER-INVESTOR-SELECTION.md` for the qualification and approval rules.
