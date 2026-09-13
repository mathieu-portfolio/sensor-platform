SELECT r.run_id, scenario_seed, layout_seed, duration_seconds, target_count,
       sensor_count, evaluated_frames, target_samples, matched_samples,
       position_rmse, mean_position_error, missed_target_samples,
       false_track_samples, unique_false_tracks, id_switches
FROM runs r JOIN run_metrics m USING (run_id)
ORDER BY run_id;
