-- Adds quarter-over-quarter 13F change tracking for existing Supabase projects.
-- New projects already get this table through 001_initial_truth_store.sql.

CREATE TABLE IF NOT EXISTS holding_changes (
  id bigserial PRIMARY KEY,
  investor_id bigint NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  current_filing_id bigint REFERENCES filings(id) ON DELETE SET NULL,
  previous_filing_id bigint REFERENCES filings(id) ON DELETE SET NULL,
  quarter text NOT NULL,
  previous_quarter text,
  change_type text NOT NULL,
  shares_current numeric,
  shares_previous numeric,
  shares_delta numeric,
  market_value_current numeric,
  market_value_previous numeric,
  market_value_delta numeric,
  pct_portfolio_current numeric,
  pct_portfolio_previous numeric,
  source text NOT NULL DEFAULT '13f-change-engine',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(investor_id, security_id, quarter, source)
);

CREATE INDEX IF NOT EXISTS idx_holding_changes_quarter ON holding_changes(quarter, change_type);
CREATE INDEX IF NOT EXISTS idx_holding_changes_security ON holding_changes(security_id, quarter);
