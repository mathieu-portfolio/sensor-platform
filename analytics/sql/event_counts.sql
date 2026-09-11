SELECT run_id, run_generation, event_type, count(*) AS event_count
FROM events GROUP BY ALL
ORDER BY run_id, run_generation, event_type;
