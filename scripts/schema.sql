CREATE TABLE IF NOT EXISTS rate_quotes (
  id UUID PRIMARY KEY, source VARCHAR(80) NOT NULL, origin VARCHAR(120) NOT NULL,
  destination VARCHAR(120) NOT NULL, equipment VARCHAR(40) NOT NULL,
  amount NUMERIC(12,2) NOT NULL CHECK (amount > 0), currency CHAR(3) NOT NULL DEFAULT 'USD',
  quoted_at TIMESTAMPTZ NOT NULL, expires_at TIMESTAMPTZ, metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source, origin, destination, equipment, quoted_at)
);
CREATE INDEX IF NOT EXISTS ix_rate_quotes_route_time ON rate_quotes(origin, destination, quoted_at);
CREATE TABLE IF NOT EXISTS rate_consensus (
  id UUID PRIMARY KEY, origin VARCHAR(120) NOT NULL, destination VARCHAR(120) NOT NULL,
  equipment VARCHAR(40) NOT NULL, amount NUMERIC(12,2) NOT NULL,
  currency CHAR(3) NOT NULL DEFAULT 'USD', quote_count INTEGER NOT NULL,
  sources JSONB NOT NULL DEFAULT '[]'::jsonb, calculated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
