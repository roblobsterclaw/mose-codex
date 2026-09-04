-- Preserve Joe-style nomination reasoning and original filing provenance.

ALTER TABLE mose_codex_investor_candidates
  ADD COLUMN IF NOT EXISTS profile_fit_score numeric,
  ADD COLUMN IF NOT EXISTS style_lane text,
  ADD COLUMN IF NOT EXISTS philosophy_evidence_status text,
  ADD COLUMN IF NOT EXISTS filing_urls jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS fund_value_ratio numeric;

CREATE INDEX IF NOT EXISTS idx_mose_codex_candidates_lane
  ON mose_codex_investor_candidates
  (workspace_key, source_quarter, style_lane, profile_fit_score DESC);

INSERT INTO mose_codex_schema_migrations (version)
VALUES ('002_codex_investor_candidate_profile')
ON CONFLICT (version) DO NOTHING;
