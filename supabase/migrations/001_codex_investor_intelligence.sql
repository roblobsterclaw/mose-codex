-- Independent MOSE Codex investor-selection and monitoring tables.
-- These table names are intentionally isolated from the production MOSE schema.

CREATE TABLE IF NOT EXISTS mose_codex_schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mose_codex_investor_candidates (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  source_quarter text NOT NULL,
  cik text NOT NULL,
  manager_name text NOT NULL,
  fund_name text,
  status text NOT NULL CHECK (status IN ('candidate', 'approved', 'rejected')),
  score numeric NOT NULL,
  candidate_rank integer,
  positions integer,
  total_value_usd numeric,
  top10_weight numeric,
  turnover_8q numeric,
  median_hold_q numeric,
  history_quarters integer,
  long_only_value_ratio numeric,
  meets_quantitative_screen boolean NOT NULL DEFAULT false,
  screen_failures jsonb NOT NULL DEFAULT '[]'::jsonb,
  score_components jsonb NOT NULL DEFAULT '{}'::jsonb,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  generated_at timestamptz NOT NULL,
  PRIMARY KEY (workspace_key, source_quarter, cik)
);

CREATE TABLE IF NOT EXISTS mose_codex_investor_decisions (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  cik text NOT NULL,
  decision text NOT NULL CHECK (decision IN ('approve', 'reject')),
  reason text NOT NULL,
  decided_at timestamptz NOT NULL,
  decided_by text NOT NULL DEFAULT 'Joe Lynch',
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (workspace_key, cik)
);

CREATE TABLE IF NOT EXISTS mose_codex_investor_sources (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  source_key text NOT NULL,
  cik text NOT NULL,
  investor_name text NOT NULL,
  source_type text NOT NULL,
  source_url text NOT NULL,
  source_kind text,
  first_party boolean NOT NULL DEFAULT true,
  enabled boolean NOT NULL DEFAULT true,
  verified_at timestamptz,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_key, source_key)
);

CREATE TABLE IF NOT EXISTS mose_codex_investor_signals (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  signal_id text NOT NULL,
  observed_at timestamptz NOT NULL,
  kind text NOT NULL,
  form text,
  investor_name text,
  investor_cik text,
  ticker text,
  cusip text,
  company text,
  direction text NOT NULL DEFAULT 'neutral',
  confidence numeric,
  summary text,
  source_url text NOT NULL,
  source_title text,
  source_class text NOT NULL,
  affects_conviction boolean NOT NULL DEFAULT false,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_key, signal_id)
);

CREATE TABLE IF NOT EXISTS mose_codex_investors (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  cik text NOT NULL,
  investor_name text NOT NULL,
  fund_name text,
  tier integer,
  active boolean NOT NULL DEFAULT true,
  approval_status text NOT NULL DEFAULT 'approved',
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_key, cik)
);

CREATE TABLE IF NOT EXISTS mose_codex_securities (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  cusip text NOT NULL,
  ticker text,
  company_name text,
  resolution_status text NOT NULL DEFAULT 'unresolved',
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_key, cusip)
);

CREATE TABLE IF NOT EXISTS mose_codex_filings (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  accession text NOT NULL,
  investor_cik text NOT NULL,
  form text NOT NULL,
  report_quarter text NOT NULL,
  period_end date,
  filing_date date,
  total_value_usd numeric,
  holding_count integer,
  source_url text,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_key, accession),
  FOREIGN KEY (workspace_key, investor_cik)
    REFERENCES mose_codex_investors (workspace_key, cik)
);

CREATE TABLE IF NOT EXISTS mose_codex_holdings (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  accession text NOT NULL,
  investor_cik text NOT NULL,
  report_quarter text NOT NULL,
  cusip text NOT NULL,
  ticker text,
  company_name text,
  shares numeric,
  market_value_usd numeric,
  pct_portfolio numeric,
  rank_in_portfolio integer,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_key, accession, cusip),
  FOREIGN KEY (workspace_key, accession)
    REFERENCES mose_codex_filings (workspace_key, accession),
  FOREIGN KEY (workspace_key, investor_cik)
    REFERENCES mose_codex_investors (workspace_key, cik),
  FOREIGN KEY (workspace_key, cusip)
    REFERENCES mose_codex_securities (workspace_key, cusip)
);

CREATE TABLE IF NOT EXISTS mose_codex_holding_changes (
  workspace_key text NOT NULL DEFAULT 'mose-codex',
  investor_cik text NOT NULL,
  report_quarter text NOT NULL,
  previous_quarter text,
  cusip text NOT NULL,
  ticker text,
  change_type text NOT NULL,
  shares_current numeric,
  shares_previous numeric,
  market_value_current_usd numeric,
  market_value_previous_usd numeric,
  pct_portfolio_current numeric,
  pct_portfolio_previous numeric,
  source_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (workspace_key, investor_cik, report_quarter, cusip),
  FOREIGN KEY (workspace_key, investor_cik)
    REFERENCES mose_codex_investors (workspace_key, cik),
  FOREIGN KEY (workspace_key, cusip)
    REFERENCES mose_codex_securities (workspace_key, cusip)
);

CREATE INDEX IF NOT EXISTS idx_mose_codex_candidates_score
  ON mose_codex_investor_candidates (workspace_key, source_quarter, status, score DESC);
CREATE INDEX IF NOT EXISTS idx_mose_codex_signals_time
  ON mose_codex_investor_signals (workspace_key, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_mose_codex_signals_investor
  ON mose_codex_investor_signals (workspace_key, investor_cik, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_mose_codex_holdings_investor_quarter
  ON mose_codex_holdings (workspace_key, investor_cik, report_quarter);
CREATE INDEX IF NOT EXISTS idx_mose_codex_holdings_security_quarter
  ON mose_codex_holdings (workspace_key, cusip, report_quarter);
CREATE INDEX IF NOT EXISTS idx_mose_codex_changes_quarter
  ON mose_codex_holding_changes (workspace_key, report_quarter, change_type);

ALTER TABLE mose_codex_investor_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_schema_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_investor_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_investor_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_investor_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_investors ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_securities ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_filings ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_holdings ENABLE ROW LEVEL SECURITY;
ALTER TABLE mose_codex_holding_changes ENABLE ROW LEVEL SECURITY;

INSERT INTO mose_codex_schema_migrations (version)
VALUES ('001_codex_investor_intelligence')
ON CONFLICT (version) DO NOTHING;
