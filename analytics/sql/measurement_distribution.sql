-- Actual measurement-level volume, share and uncertainty, independently grouped per generation.
SELECT run_id, run_generation, sensor_id, count(*) AS detections,
       100.0 * count(*) / sum(count(*)) OVER (PARTITION BY run_id, run_generation) AS volume_pct,
       avg(confidence) AS mean_confidence,
       avg(uncertainty_radius) AS mean_uncertainty_radius,
       min(x) AS min_x, max(x) AS max_x, min(y) AS min_y, max(y) AS max_y
FROM measurements GROUP BY run_id, run_generation, sensor_id
ORDER BY run_id, run_generation, sensor_id;
