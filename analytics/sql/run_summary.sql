-- Do not subtract timestamps across world resets. Report each generation separately.
WITH lifecycle AS (
    SELECT run_id, run_generation, count(*) AS events,
           max(event_time_seconds) AS last_event_time_seconds,
           count(DISTINCT sensor_id) AS sensors
    FROM events GROUP BY ALL
), volume AS (
    SELECT run_id, run_generation, count(*) AS scans, sum(measurement_count) AS detections
    FROM scans GROUP BY ALL
)
SELECT l.*, coalesce(v.scans, 0) AS scans, coalesce(v.detections, 0) AS detections
FROM lifecycle l LEFT JOIN volume v USING (run_id, run_generation)
ORDER BY run_id, run_generation;
