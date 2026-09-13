# Deterministic analytical sweeps

Build the selected runtime explicitly, then run the small included sensor-quality
fixture (3 noise levels × 3 scenario seeds = 9 four-second runs):

```powershell
python scripts/dev.py build --target sensor_platform
python scripts/dev.py sweep --output data/sweeps/sensor-quality
# Or choose a JSON specification and an existing build:
python scripts/dev.py --build-dir build sweep --spec experiments/configs/sensor-quality.json --output data/sweeps/another-run
```

The output directory must not exist. Reruns use a new directory; existing results
are never overwritten. Runs execute sequentially without implicit builds,
dependency installation, brokers, viewers, or worker processes beyond the runtime
commands. A failed run aborts the sweep and reports its error; the temporary
experiment directory is removed, and no incomplete dataset is published. There
is no resume or scheduling layer.

## Specification

```json
{
  "version": 1,
  "name": "sensor-quality",
  "seeds": [2026, 2027, 2028],
  "fixed": {"duration": 4, "sensor_layout_seed": 73, "target_count": 4},
  "vary": {"noise": [0, 1, 3], "reliability": [0.7, 1]}
}
```

Every varying parameter has an explicit nonempty value list. The Cartesian
product is crossed with every seed (18 runs in the example above). Alternatively,
`"seeds": {"start": 2026, "stop": 2029, "step": 1}` uses an exclusive stop.
Seeds set `scenario_seed`, so target generation is paired across parameter
combinations. `sensor_layout_seed` is independent: keep it fixed to compare the
same sensor network or vary it explicitly. A scenario seed does not reseed radar
noise; radar seeds continue to come from the existing layout generator.

All existing procedural parameters are supported in `fixed` or `vary`:

| Parameter | Allowed values |
| --- | --- |
| `duration` | Integer seconds, 4..120 |
| `target_count`, `sensor_count` | Integers, 1..12 and 1..8 |
| `sensor_layout_seed` | uint32 |
| `speed_min`, `speed_max` | 1..30, min <= max (generator scales by 20/duration) |
| `maneuver` | 0..3 |
| `convergence` | 0..1 |
| `spawn_spread` | 0.4..1.5 |
| `coverage` | 0.65..1.6 |
| `layout_spread` | 0.25..3 |
| `noise` | 0..5 |
| `reliability` | 0.35..1, detection probability multiplier |
| `clutter` | 0..12 |

Unspecified fixed parameters use existing procedural defaults, expanded and
persisted in `spec.json` and each run's `config.json`. A parameter cannot appear
in both `fixed` and `vary`. Unknown names, invalid values, duplicate seeds/values,
and grids above 4096 runs are rejected before execution.

The canonical resolved specification (including name) determines the SHA-256
`experiment_id`. Each effective requested configuration, including both seeds,
determines a nonzero uint64 `run_id` using the first 64 hash bits; collisions are
checked before execution. List/key ordering does not change identities or run
order. Changing an experiment name changes experiment identity but preserves run
identity for the same configuration. IDs identify configuration, not a binary
version; the manifest records the runtime executable hash. Deterministic results
are expected for the same runtime, core, and tooling environment, not guaranteed
across compiler/platform/dependency changes.

## Dataset

The whole experiment is published by one directory rename after all runs and
both experiment tables are complete:

- `experiments.parquet`: one row per experiment/run, with `experiment_id`,
  `experiment_name`, `seed`, uint64 `run_id`, `requested_config` and
  `varying_parameters` JSON strings, plus every typed column from analytical
  `runs` (effective runtime parameters, counts, duration, seeds, generator version).
- `experiment_metrics.parquet`: one row per experiment/run, with experiment
  identity and seed, all existing `run_metrics` columns (RMSE/mean error, matches,
  misses, false tracks, ID switches, evaluator/fusion settings), plus
  `scan_count`, `measurement_count`, `empty_scan_count`, `scans_per_second`,
  `measurements_per_second`, and `measurements_per_scan`.
- `dataset/`: shared existing raw/clean/analysis dataset containing every run's
  events, scans, measurements, metadata, truth, tracks and metrics. It is directly
  readable with `analytics.analysis.open_analysis(output / "dataset")`.
- `runs/run_id=<id>/`: individual `scenario.config`, `config.json`, truth-free
  `recording.events`, existing fusion `tracks.jsonl`, and `analytical/` CSV files.
- `spec.json`, `manifest.json`: resolved specification, experiment identity,
  run count, executable hash and experiment-table checksums.

Rates divide observed totals by simulation duration, including scans at both
endpoints. Measurement counts include clutter; they are not detection recall.
Misses and false-track samples retain the existing evaluator's sample grain;
RMSE remains null for runs with no matches. Evaluation uses the existing default
fusion configuration and 5 m evaluation gate. Sweeps do not change those algorithms.
Truth stays separate from recording/ingestion and is consumed only by the existing
explicit analytical exporter and evaluator.

DuckDB can query the tables directly, with no new query service:

```sql
SELECT e.noise, count(*) AS runs, avg(m.position_rmse) AS mean_run_rmse,
       sum(m.missed_target_samples) AS missed_samples,
       sum(m.false_track_samples) AS false_samples, sum(m.id_switches) AS id_switches
FROM read_parquet('data/sweeps/sensor-quality/experiments.parquet') e
JOIN read_parquet('data/sweeps/sensor-quality/experiment_metrics.parquet') m
  USING (experiment_id, run_id)
GROUP BY e.noise ORDER BY e.noise;
```

Focused checks (after building) use the selected `.venv`/runtime via the developer
router: `python scripts/dev.py test experiments -k parameter_sweep`.

Use `python scripts/dev.py analysis <sweep-output>` to produce the
[canonical sensor analyses](canonical-analyses.md) from these stored tables,
without rerunning the sweep.
