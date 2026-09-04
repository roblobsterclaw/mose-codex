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
- Four-times-daily monitoring of approved investors' structured filings once
  an SEC-capable collector passes the transport check.
- Verified first-party source registry for letters, interviews, podcasts, and
  posts.
- Audited JSON exports and an isolated Supabase migration ready to connect.

## Isolation and live status

- Working copy: `/Users/joemac/Documents/mose-codex`
- Repository: `https://github.com/roblobsterclaw/mose-codex`
- Preview: `https://roblobsterclaw.github.io/mose-codex/`
- Browser state namespace: `/mose-codex`
- Supabase namespace: tables prefixed with `mose_codex_`

The Supabase migration is not applied until this repository receives its own
`SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` secrets. Scheduled SEC jobs are
paused while `SEC_TRANSPORT_READY=false`; manual runs remain available. This
state is intentional and must not be presented as successful live monitoring.

See `docs/SUPER-INVESTOR-SELECTION.md` for the qualification and approval rules.
