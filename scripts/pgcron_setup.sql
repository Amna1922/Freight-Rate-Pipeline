SELECT cron.schedule(
  'purge-expired-freight-data',
  '0 * * * *',
  $$
  DELETE FROM raw_freight_data WHERE retrieved_at < NOW() - INTERVAL '7 days';
  DELETE FROM consensus_freight_rates WHERE served_at < NOW() - INTERVAL '7 days';
  DELETE FROM audit_log WHERE created_at < NOW() - INTERVAL '7 days';
  $$
);
