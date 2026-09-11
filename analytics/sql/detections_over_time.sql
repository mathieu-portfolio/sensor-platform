-- One-second acquisition buckets include empty scans; late samples stay at actual acquisition time.
SELECT run_id, run_generation, sensor_id,
       floor(acquisition_time_seconds)::BIGINT AS simulation_second,
       count(*) AS scans, sum(measurement_count) AS detections,
       count(*) FILTER (WHERE measurement_count = 0) AS empty_scans
FROM scans GROUP BY ALL
ORDER BY run_id, run_generation, simulation_second, sensor_id;
