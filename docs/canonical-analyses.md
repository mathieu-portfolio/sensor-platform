# Canonical sensor analyses

Analyze an **existing sweep**; this command never builds or runs simulation,
fusion, ingestion, or evaluation:

```powershell
python scripts/dev.py analysis data/sweeps/sensor-quality
# Default destination: data/sweeps/sensor-quality/canonical_analysis
python scripts/dev.py analysis data/sweeps/sensor-quality --output data/reports/noise
```

Output must be a new directory. Input Parquet checksums and experiment/run/seed
membership are checked before aggregation. Publication uses one directory rename,
so a failed analysis does not expose a partial report. Source tables and individual
run artifacts are preserved. Repeat analysis into a different directory produces
the same outputs with the same SQL and DuckDB version.

## Questions and outputs

Each report includes all five metric selections. A selection with only one
parameter level is descriptive of that condition, not evidence of a relationship.
`summary.json` lists observed parameter levels explicitly.

| Output basename | Primary quantities |
| --- | --- |
| `noise` | Position RMSE, missed target samples/fraction, ID switches |
| `reliability` | Measurement count, measurements/s and /scan, missed target samples/fraction, RMSE |
| `clutter` | False track samples, unique false tracks, RMSE, measurement count |
| `convergence` | ID switches, false track samples, unique false tracks, RMSE |
| `sensor_network` | Measurement count, measurements/s and /scan, RMSE; sensor count and coverage are explicit columns |

Each selection has `.parquet` and `.csv` outputs in long form: one row per
experiment × complete condition × metric. Columns include:

- `experiment_id`, `experiment_name`, `condition_id`, and complete `condition` JSON;
- typed `noise`, `reliability`, `clutter`, `convergence`, `sensor_count`, `coverage`;
- `metric`, `unit`, `definition`;
- `run_count`, `seed_count`, actual `seeds`, `valid_count`, `null_count`;
- `mean`, `stddev` (sample standard deviation), `minimum`, `maximum`.

A condition fixes **all** procedural settings except scenario seed, including
layout seed and duration, plus generator and evaluation settings. Multi-parameter
grids remain separate cells; no implicit marginal averaging hides different
controls. Separate experiments are not pooled. Compare rows with matching other
controls and seed sets. The seed list exposes incomplete/unbalanced comparisons;
there is no confidence interval, significance test, causal estimator or trend fit.
The full precision results retain counterintuitive and non-monotonic outcomes.

`individual_runs.parquet` preserves the complete joined experiment/metric rows
and condition identifiers for distribution queries. `metric_definitions.csv`
records definitions. `statistics.sql` is the exact substantive SQL used, copied
from `analytics/sql/canonical/statistics.sql`. `summary.json` records counts,
parameter levels, caveats, source-table hashes, source executable hash, SQL hash,
DuckDB version, and output checksums. No wall-clock timestamps or output-specific
absolute paths are added.

## Metric interpretation

- Position RMSE is in metres over matched non-tentative tracks within the stored
  evaluation gate. Its mean averages **per-run RMSE equally**, rather than pooling
  target samples. A run with no matches has null RMSE, not zero. `valid_count` and
  `null_count` expose this exclusion. Mean/min/max stay null if all runs are null;
  sample standard deviation is null with fewer than two valid runs.
- Misses are unmatched **target samples**, not distinct missed targets. The missed
  fraction divides misses by target samples within each run. Out-of-coverage
  targets are included. ID switches retain the existing evaluator's definition.
- Measurement yield includes clutter; it is not detection recall. Rates use
  simulated seconds, including endpoint scans. Measurements/scan normalizes by
  observed sensor scans, not by truth visibility or detection opportunities.
- False track samples count unmatched non-tentative tracks at evaluated times;
  unique false tracks count IDs unmatched at least once. Stored sweep data has no
  per-measurement truth labels, so **false sensor-return counts cannot be recovered**.
  The suite does not invent such labels or equate false tracks with false returns.
- Sensor count changes the generator's network geometry and cadence composition,
  not merely the number of identical sensors. Coverage has an existing floor, so
  changing its multiplier may leave effective ranges unchanged. Inspect retained
  sensor metadata when interpreting either comparison.

## Small canonical specifications

The five `experiments/configs/canonical-*.json` files each use two deterministic
scenario seeds, three parameter levels and a four-second duration (6 runs each):

| Spec suffix | Values |
| --- | --- |
| `noise` | noise = 0, 1, 3 |
| `reliability` | reliability = 0.5, 0.75, 1 |
| `clutter` | clutter = 0, 4, 12 |
| `convergence` | convergence = 0, 0.5, 1 |
| `sensor-network` | sensor_count = 1, 2, 3 |

Unspecified parameters use the sweep engine's stored defaults; layout seed is
fixed at 73. These are fast validation fixtures, not adequately powered studies.
The generator scales speed by 20/duration; these short runs are comparatively
fast-moving, and their results must not be generalized to longer scenarios.
The earlier `sensor-quality.json` dataset also works without regeneration.

When new representative data is needed, use the separate existing sweep command:

```powershell
python scripts/dev.py build --target sensor_platform
python scripts/dev.py sweep --spec experiments/configs/canonical-clutter.json --output data/sweeps/canonical-clutter
python scripts/dev.py analysis data/sweeps/canonical-clutter
```

For direct inspection in DuckDB:

```sql
SELECT clutter, run_count, metric, mean, stddev, minimum, maximum, unit
FROM read_parquet('data/sweeps/canonical-clutter/canonical_analysis/clutter.parquet')
ORDER BY clutter, metric;
```

Focused SQL/export tests use only synthetic stored tables:
`python scripts/dev.py test analytics -k test_canonical`.

## Representative validation observations

Inspected DuckDB/Parquet and CSV outputs under `data/sweeps/*/canonical_analysis`.
Noise reuses the stored 9-run `sensor-quality` sweep (seeds 2026..2028); the other
four fixtures use seeds 2026 and 2027 (6 runs each). Values below are means across
those runs, not significance estimates. Spread and every individual run remain
in the generated outputs.

| Varying values | Observed per-run means |
| --- | --- |
| Noise 0 / 1 / 3 | RMSE 1.7352 / 2.0131 / 2.9853 m; missed samples 20 / 18 / 37.3333; ID switches 8 / 8 / 6.3333 |
| Reliability 0.5 / 0.75 / 1 | Measurements 63.5 / 88.5 / 115.5; misses 41.5 / 35 / 17.5; RMSE 2.7801 / 2.5197 / 1.9885 m |
| Clutter 0 / 4 / 12 | False track samples 18.5 / 23 / 30; RMSE 1.9885 / 2.0348 / 2.0454 m |
| Convergence 0 / 0.5 / 1 | ID switches 1.5 / 1.5 / 10.5; RMSE 2.0305 / 1.8601 / 1.9885 m |
| Sensors 1 / 2 / 3 | Measurements 60.5 / 80 / 115.5; RMSE 2.6468 / 2.2921 / 1.9885 m |

Noise 0?1 reduced misses despite increased RMSE, and convergence RMSE was lowest
at the middle setting. Lower ID switches at the highest noise level coincided
with substantially more misses, so that count alone does not establish better
tracking. False tracks existed even at zero clutter: unmatched tracks under the
evaluation gate are not a direct measurement of false sensor returns. These
observations concern short, fast-moving fixtures and very few target seeds.
