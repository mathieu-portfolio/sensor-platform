-- A condition fixes every procedural parameter except scenario seed. Retain
-- layout seed, generator and evaluation settings: never pool unlike controls.
CREATE VIEW individual_runs AS
SELECT e.*, m.* EXCLUDE (experiment_id, experiment_name, seed, run_id),
       to_json(struct_pack(
           generator_version := e.generator_version, layout_seed := e.layout_seed,
           duration_seconds := e.duration_seconds, target_count := e.target_count,
           sensor_count := e.sensor_count, tick_hz := e.tick_hz,
           speed_min := e.speed_min, speed_max := e.speed_max, maneuver := e.maneuver,
           convergence := e.convergence, spawn_spread := e.spawn_spread,
           coverage := e.coverage, layout_spread := e.layout_spread,
           noise := e.noise, reliability := e.reliability, clutter := e.clutter,
           evaluator_version := m.evaluator_version, fusion_config := m.fusion_config,
           evaluation_gate := m.evaluation_gate)) AS condition,
       sha256(condition) AS condition_id
FROM experiments e JOIN experiment_metrics m USING (experiment_id, run_id, seed, experiment_name);

CREATE VIEW metric_definitions AS
SELECT * FROM (VALUES
 ('position_rmse', 'm', 'Per-run RMSE of matched confirmed/coasting tracks within the evaluation gate; null if no matches. Mean is equal-weight across non-null runs, not pooled sample RMSE.'),
 ('missed_target_samples', 'target-samples/run', 'Unmatched truth target samples at evaluated scan timestamps, including out-of-coverage targets; not distinct missed targets.'),
 ('missed_target_fraction', 'fraction', 'Missed target samples / target samples within each run; null if denominator is zero.'),
 ('id_switches', 'switches/run', 'Changes in matched track identity for a previously matched truth target using the existing evaluator.'),
 ('measurement_count', 'measurements/run', 'All recorded measurements, including clutter; not true detections or recall.'),
 ('measurements_per_second', 'measurements/s', 'Total measurements divided by simulation duration, including endpoint scans.'),
 ('measurements_per_scan', 'measurements/scan', 'Total measurements divided by all sensor scans; includes clutter.'),
 ('false_track_samples', 'track-samples/run', 'Unmatched non-tentative tracks at evaluated timestamps; not false sensor returns.'),
 ('unique_false_tracks', 'tracks/run', 'Distinct tracks unmatched at least once, as counted by the existing evaluator; not distinct false returns.')
) AS t(metric, unit, definition);

CREATE VIEW run_values AS
SELECT r.experiment_id, r.experiment_name, r.condition_id, r.condition, r.run_id, r.seed,
       v.metric, v.value::DOUBLE AS value
FROM individual_runs r,
LATERAL (VALUES
 ('position_rmse', r.position_rmse),
 ('missed_target_samples', r.missed_target_samples),
 ('missed_target_fraction', r.missed_target_samples::DOUBLE / nullif(r.target_samples, 0)),
 ('id_switches', r.id_switches),
 ('measurement_count', r.measurement_count),
 ('measurements_per_second', r.measurements_per_second),
 ('measurements_per_scan', r.measurements_per_scan),
 ('false_track_samples', r.false_track_samples),
 ('unique_false_tracks', r.unique_false_tracks)
) AS v(metric, value);

CREATE VIEW condition_statistics AS
SELECT experiment_id, experiment_name, condition_id, condition, metric,
       count(*) AS run_count, count(DISTINCT seed) AS seed_count,
       list(seed ORDER BY seed) AS seeds,
       count(value) AS valid_count, count(*) - count(value) AS null_count,
       avg(value) AS mean, stddev_samp(value) AS stddev,
       min(value) AS minimum, max(value) AS maximum
FROM run_values
GROUP BY experiment_id, experiment_name, condition_id, condition, metric;

CREATE VIEW canonical_statistics AS
SELECT a.analysis,
       (s.condition::JSON->>'noise')::DOUBLE AS noise,
       (s.condition::JSON->>'reliability')::DOUBLE AS reliability,
       (s.condition::JSON->>'clutter')::DOUBLE AS clutter,
       (s.condition::JSON->>'convergence')::DOUBLE AS convergence,
       (s.condition::JSON->>'sensor_count')::INTEGER AS sensor_count,
       (s.condition::JSON->>'coverage')::DOUBLE AS coverage,
       s.*, d.unit, d.definition
FROM condition_statistics s JOIN metric_definitions d USING(metric)
JOIN (VALUES
 ('noise', 'position_rmse'), ('noise', 'missed_target_samples'),
 ('noise', 'missed_target_fraction'), ('noise', 'id_switches'),
 ('reliability', 'measurement_count'), ('reliability', 'measurements_per_second'),
 ('reliability', 'measurements_per_scan'), ('reliability', 'missed_target_samples'),
 ('reliability', 'missed_target_fraction'), ('reliability', 'position_rmse'),
 ('clutter', 'false_track_samples'), ('clutter', 'unique_false_tracks'),
 ('clutter', 'position_rmse'), ('clutter', 'measurement_count'),
 ('convergence', 'id_switches'), ('convergence', 'false_track_samples'),
 ('convergence', 'unique_false_tracks'), ('convergence', 'position_rmse'),
 ('sensor_network', 'measurement_count'), ('sensor_network', 'measurements_per_second'),
 ('sensor_network', 'measurements_per_scan'), ('sensor_network', 'position_rmse')
) a(analysis, metric) USING(metric);
