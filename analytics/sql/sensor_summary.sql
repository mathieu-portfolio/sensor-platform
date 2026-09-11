-- Include sensors that started but never completed a scan. Do not multiply scans by detections.
WITH started AS (
    SELECT run_id, run_generation, sensor_id FROM events
    WHERE event_type = 'SENSOR_STARTED'
), scan_totals AS (
    SELECT run_id, run_generation, sensor_id,
           count(*) AS scans, count(*) FILTER (WHERE measurement_count = 0) AS empty_scans,
           sum(measurement_count) AS detections
    FROM scans GROUP BY ALL
)
SELECT s.run_id, s.run_generation, s.sensor_id,
       coalesce(t.scans, 0) AS scans, coalesce(t.detections, 0) AS detections,
       coalesce(t.empty_scans, 0) AS empty_scans,
       100.0 * t.empty_scans / nullif(t.scans, 0) AS empty_scan_pct,
       t.detections::DOUBLE / nullif(t.scans, 0) AS detections_per_scan
FROM started s LEFT JOIN scan_totals t USING (run_id, run_generation, sensor_id)
ORDER BY s.run_id, s.run_generation, s.sensor_id;
