-- MOSE symbol snapshot foundation.
-- Apply this after 001 if your Supabase project already has the initial tables.

ALTER TABLE securities ADD COLUMN IF NOT EXISTS display_name text;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS exchange text;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS sector text;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS industry text;
ALTER TABLE securities ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true;

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

ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS change_pct numeric;
ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS volume numeric;
ALTER TABLE price_snapshots ADD COLUMN IF NOT EXISTS market_status text;

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

CREATE INDEX IF NOT EXISTS idx_market_symbols_active ON market_symbols(active, topbar, sort_order);
CREATE INDEX IF NOT EXISTS idx_price_history_security_date ON price_history(security_id, price_date);
CREATE INDEX IF NOT EXISTS idx_symbol_metrics_security_date ON symbol_metrics(security_id, metric_date);

INSERT INTO schema_migrations (version)
VALUES ('002_symbol_snapshots')
ON CONFLICT (version) DO NOTHING;
