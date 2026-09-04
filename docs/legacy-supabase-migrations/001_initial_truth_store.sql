-- MOSE Supabase/Postgres migration.
-- Keep this aligned with db/schema.sql while the local SQLite schema hardens.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investors (
  id bigserial PRIMARY KEY,
  name text NOT NULL UNIQUE,
  fund text,
  tier integer NOT NULL,
  source_type text NOT NULL DEFAULT '13F',
  cik text,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS filings (
  id bigserial PRIMARY KEY,
  investor_id bigint NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
  source text NOT NULL,
  accession text,
  filing_date date,
  report_period date,
  total_value numeric,
  num_holdings integer,
  raw_payload jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(investor_id, source, accession)
);

CREATE TABLE IF NOT EXISTS securities (
  id bigserial PRIMARY KEY,
  ticker text NOT NULL UNIQUE,
  company text,
  cusip text,
  asset_type text NOT NULL DEFAULT 'equity',
  display_name text,
  exchange text,
  sector text,
  industry text,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_symbols (
  id bigserial PRIMARY KEY,
  security_id bigint REFERENCES securities(id) ON DELETE CASCADE,
  symbol text NOT NULL UNIQUE,
  label text NOT NULL,
  symbol_type text NOT NULL DEFAULT 'equity',
  provider_symbol text,
  topbar boolean NOT NULL DEFAULT false,
  chart_enabled boolean NOT NULL DEFAULT true,
  active boolean NOT NULL DEFAULT true,
  sort_order integer NOT NULL DEFAULT 100,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS holdings (
  id bigserial PRIMARY KEY,
  filing_id bigint NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
  investor_id bigint NOT NULL REFERENCES investors(id) ON DELETE CASCADE,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  shares numeric,
  market_value numeric,
  pct_of_portfolio numeric,
  rank_in_portfolio integer,
  is_top5 boolean NOT NULL DEFAULT false,
  source text NOT NULL DEFAULT 'convergence-master.json',
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(filing_id, security_id)
);

CREATE TABLE IF NOT EXISTS convergence_rankings (
  id bigserial PRIMARY KEY,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  generated_at timestamptz NOT NULL,
  convergence_score numeric NOT NULL DEFAULT 0,
  total_investor_count integer NOT NULL DEFAULT 0,
  tier1_count integer NOT NULL DEFAULT 0,
  tier2_count integer NOT NULL DEFAULT 0,
  tier3_count integer NOT NULL DEFAULT 0,
  total_conviction_pct numeric NOT NULL DEFAULT 0,
  total_value_held numeric NOT NULL DEFAULT 0,
  top5_bonus_count integer NOT NULL DEFAULT 0,
  raw_investors jsonb NOT NULL DEFAULT '[]'::jsonb,
  UNIQUE(security_id, generated_at)
);

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

CREATE TABLE IF NOT EXISTS price_snapshots (
  id bigserial PRIMARY KEY,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  price numeric NOT NULL,
  currency text NOT NULL DEFAULT 'USD',
  change_pct numeric,
  volume numeric,
  market_status text,
  source text NOT NULL,
  fetched_at timestamptz NOT NULL,
  raw_payload jsonb,
  UNIQUE(security_id, source, fetched_at)
);

CREATE TABLE IF NOT EXISTS price_history (
  id bigserial PRIMARY KEY,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  price_date date NOT NULL,
  open numeric,
  high numeric,
  low numeric,
  close numeric NOT NULL,
  volume numeric,
  source text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(security_id, price_date, source)
);

CREATE TABLE IF NOT EXISTS symbol_metrics (
  id bigserial PRIMARY KEY,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  metric_date date NOT NULL,
  market_cap numeric,
  pe_ratio numeric,
  forward_pe numeric,
  dividend_yield numeric,
  beta numeric,
  eps_ttm numeric,
  revenue_growth numeric,
  week_52_high numeric,
  week_52_low numeric,
  source text NOT NULL,
  raw_payload jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(security_id, metric_date, source)
);

CREATE TABLE IF NOT EXISTS symbol_profiles (
  id bigserial PRIMARY KEY,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  description text,
  website text,
  logo_url text,
  country text,
  exchange text,
  source text NOT NULL,
  raw_payload jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(security_id, source)
);

CREATE TABLE IF NOT EXISTS portfolio_accounts (
  id bigserial PRIMARY KEY,
  name text NOT NULL UNIQUE,
  brokerage text,
  account_type text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS portfolio_lots (
  id bigserial PRIMARY KEY,
  account_id bigint REFERENCES portfolio_accounts(id) ON DELETE SET NULL,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  shares numeric NOT NULL,
  cost_basis_per_share numeric,
  opened_at date,
  source text NOT NULL DEFAULT 'manual',
  broker_lot_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
  id bigserial PRIMARY KEY,
  security_id bigint REFERENCES securities(id) ON DELETE SET NULL,
  signal_type text NOT NULL,
  confidence text NOT NULL DEFAULT 'unverified',
  severity text NOT NULL DEFAULT 'info',
  summary text NOT NULL,
  source text NOT NULL,
  observed_at timestamptz NOT NULL DEFAULT now(),
  raw_payload jsonb
);

CREATE TABLE IF NOT EXISTS research_items (
  id bigserial PRIMARY KEY,
  security_id bigint NOT NULL REFERENCES securities(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'needs',
  priority text NOT NULL DEFAULT 'None',
  trigger_reason text,
  source text NOT NULL DEFAULT 'manual',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(security_id)
);

CREATE TABLE IF NOT EXISTS research_reports (
  id bigserial PRIMARY KEY,
  research_item_id bigint NOT NULL REFERENCES research_items(id) ON DELETE CASCADE,
  thesis text,
  risks text,
  valuation_notes text,
  portfolio_fit text,
  source_notes text,
  confidence text NOT NULL DEFAULT 'draft',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_events (
  id bigserial PRIMARY KEY,
  source text NOT NULL,
  event_type text NOT NULL,
  status text NOT NULL,
  summary text,
  payload jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS export_runs (
  id bigserial PRIMARY KEY,
  export_path text NOT NULL,
  generated_at timestamptz NOT NULL DEFAULT now(),
  investor_count integer NOT NULL DEFAULT 0,
  security_count integer NOT NULL DEFAULT 0,
  ranking_count integer NOT NULL DEFAULT 0,
  notes text
);

CREATE INDEX IF NOT EXISTS idx_holdings_investor ON holdings(investor_id);
CREATE INDEX IF NOT EXISTS idx_holdings_security ON holdings(security_id);
CREATE INDEX IF NOT EXISTS idx_filings_investor_date ON filings(investor_id, filing_date);
CREATE INDEX IF NOT EXISTS idx_rankings_generated ON convergence_rankings(generated_at);
CREATE INDEX IF NOT EXISTS idx_holding_changes_quarter ON holding_changes(quarter, change_type);
CREATE INDEX IF NOT EXISTS idx_holding_changes_security ON holding_changes(security_id, quarter);
CREATE INDEX IF NOT EXISTS idx_prices_security_fetched ON price_snapshots(security_id, fetched_at);
CREATE INDEX IF NOT EXISTS idx_market_symbols_active ON market_symbols(active, topbar, sort_order);
CREATE INDEX IF NOT EXISTS idx_price_history_security_date ON price_history(security_id, price_date);
CREATE INDEX IF NOT EXISTS idx_symbol_metrics_security_date ON symbol_metrics(security_id, metric_date);
CREATE INDEX IF NOT EXISTS idx_research_items_status ON research_items(status, priority);

INSERT INTO schema_migrations (version)
VALUES ('001_initial_truth_store')
ON CONFLICT (version) DO NOTHING;
