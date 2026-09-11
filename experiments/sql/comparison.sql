SELECT config.name AS scenario, transport, metrics.total_produced AS produced,
       metrics.total_consumed AS consumed,
       round(metrics.produced_events_per_second, 2) AS produced_eps,
       round(metrics.consumed_events_per_second, 2) AS consumed_eps,
       round(metrics.latency_p50_ms, 2) AS p50_ms,
       round(metrics.latency_p95_ms, 2) AS p95_ms,
       round(metrics.latency_p99_ms, 2) AS p99_ms,
       metrics.max_backlog AS max_backlog,
       round(metrics.catchup_seconds, 3) AS recovery_seconds,
       metrics.duplicate_count AS duplicates, metrics.missing_sequence_count AS missing,
       metrics.integrity_pass AS integrity_pass
FROM experiments ORDER BY transport, scenario;
