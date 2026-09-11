-- Samples are the last snapshot at each acquisition timestamp, after all sensors.
SELECT run_id, run_generation, track_id, min(acquisition_time) AS first_sample,
       max(acquisition_time) AS last_sample, count(*) AS samples,
       count(*) FILTER (WHERE state = 'tentative') AS tentative_samples,
       count(*) FILTER (WHERE state = 'coasting') AS coasting_samples,
       max(observations) AS observations, max(sensor_count) AS contributing_sensors,
       max(acquisition_time - last_seen) AS max_observation_age
FROM track_samples GROUP BY run_id, run_generation, track_id
ORDER BY run_id, run_generation, track_id;
