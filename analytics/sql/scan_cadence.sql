-- Observed acquisition intervals; never bridge independent sensor or world resets.
WITH intervals AS (
    SELECT *, acquisition_time_seconds -
        lag(acquisition_time_seconds) OVER (
            PARTITION BY run_id, run_generation, sensor_id, sensor_generation
            ORDER BY scan_sequence) AS interval_seconds
    FROM scans
)
SELECT run_id, run_generation, sensor_id, sensor_generation, count(*) AS scans,
       min(interval_seconds) AS min_interval_seconds,
       avg(interval_seconds) AS mean_interval_seconds,
       max(interval_seconds) AS max_interval_seconds,
       1.0 / nullif(avg(interval_seconds), 0) AS observed_hz
FROM intervals GROUP BY ALL
ORDER BY run_id, run_generation, sensor_id, sensor_generation;
