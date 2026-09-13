# Curated multi-seed study and graphical results

**Question:** How do sensor quality and sensor-network configuration affect
multi-target tracking performance?

The portfolio study is separate from the small sweep/test fixtures. It uses five
one-variable sweeps, three conditions each, and 20 paired deterministic scenario
seeds (2026..2045): **300 headless run executions, 240 distinct configurations**.
Each run lasts 20 simulated seconds. Common settings are four targets, layout
seed 73, and the generator defaults (three sensors except in the sensor-count
comparison). The complete resolved configuration is stored for every sweep/run.

| Dimension | Conditions |
| --- | --- |
| Sensor noise | 0, 1, 3 |
| Detection reliability | 0.5, 0.75, 1 |
| Clutter | 0, 4, 12 |
| Target convergence | 0, 0.5, 1 |
| Sensor network | 1, 2, 3 sensors |

Each dimension changes only its listed parameter. Shared baseline configurations
are repeated in the relevant sweeps; these are not independent additional seeds.
Sensor noise and clutter are generator multipliers, not measured error/return
rates. Sensor count changes geometry and cadence composition as well as count.
Sensor RNG seeds come from the fixed layout seed, so the 20 seeds sample target
trajectories, not independent sensor-network layouts.

## Reproduce the study

Dependencies and the sibling `sensor_core` checkout must already be available.
Reuse a configured build; builds, generation and viewing remain explicit:

```powershell
python scripts/dev.py build --target sensor_platform
python scripts/dev.py build --target sensor_platform_viewer
python scripts/dev.py study generate --output data/studies/curated
python scripts/dev.py results
```

`study generate` uses `experiments/configs/curated-study.json` unless `--spec` is
supplied. It runs the existing sweep, ingestion, fusion, evaluation and canonical
SQL infrastructure sequentially and prepares the final report/display export.
Choose a **new output directory** for regeneration. An incomplete study retains
completed sweep evidence and records the failure; it is not a completed portfolio
artifact. No scheduler, distributed workers or general workflow engine is added.

To repeat analysis over the persisted sweeps without running any simulation:

```powershell
python scripts/dev.py study analyze data/studies/curated --output data/studies/curated/reanalysis
python scripts/dev.py results data/studies/curated/reanalysis/results.view
```

`results` invokes the same optional C++/raylib graphical application used for
scenario playback, in a separate `--results` mode. It reads only the compact
`results.view` export. It does not start Python, DuckDB, simulation, fusion,
evaluation, or a sweep. Opening results does not require the runtime executable
or the full individual-run recordings. The original `viewer` command, procedural
controls and scenario playback behavior remain intact.

## Results screen

The overview shows one primary chart per dimension. Five tabs expose companion
metrics (RMSE, measurement yield, missed samples, false tracks and ID switches).
Click tabs, use Left/Right or keys 0..5, and press Escape to close. Hover a plotted
mean for its sample standard deviation and observed min/max. Whiskers show mean
+/- one sample standard deviation, clipped at zero; they are not confidence
intervals. Detail plots show valid/total runs per condition. Null RMSE appears as
"no matches", never zero. Axis units, definitions and interpretation limits are
visible. The fixed-layout, descriptive nature of this experiment is explicit.

The command supports existing screenshot/frame conventions:

```powershell
python scripts/dev.py results --page 2 --frames 3 --screenshot build/study-reliability.png
```

## Persisted outputs

Under `data/studies/curated/`:

- `definition.json`: selected study specification; `execution.json`: status,
  exact elapsed seconds and timing scope (generation through final analysis).
- `sweeps/<dimension>/`: existing immutable sweep datasets, per-run event
  recordings, analytical truth, tracks, Parquet tables and manifests.
- `analysis/<dimension>/`: canonical SQL, CSV/Parquet aggregates, individual
  rows and source/output checksums.
- `analysis/individual_runs.parquet`, `aggregates.parquet`: combined tables
  with experiment identity preserved. Shared baseline run IDs are expected;
  use `(experiment_id, run_id)` to identify memberships.
- `analysis/summary.json`: stable complete configuration, mean/SD/min/max and
  valid counts, descriptive findings, runtime/SQL/Python implementation hashes,
  DuckDB version and limitations.
- `analysis/report.md`: human-readable conditions, findings and spread tables.
- `analysis/results.view`: small versioned C++ display export; `manifest.json`
  records the top-level report/display/table checksums.

Timing lives outside the stable analytical summary. Reanalysis is reproducible
from stored sweeps with the same implementation and DuckDB version. Cross-platform
or changed compiler/runtime numerical equivalence is not promised. Full datasets
and recordings remain local generated artifacts; the README screenshot is the
only retained generated presentation asset.

Production recordings and clean event/measurement ingestion remain truth-free.
Only explicit offline evaluation joins separate analytical ground truth to track
snapshots. The results UI loads aggregates, not ground-truth IDs or associations.
False-track samples are unmatched non-tentative tracks at evaluation timestamps,
**not false sensor returns**; stored measurements have no truth labels. Matched
RMSE can look better when more difficult targets are missed, so companion metrics
are necessary. Means describe this experiment, not causal or significance claims.

## Focused validation

Small fixtures precede the portfolio execution. The full study is not a test
fixture and is never run by the tests:

```powershell
python scripts/dev.py build --target sensor_platform_results_tests
python scripts/dev.py test unit -R platform_results
python scripts/dev.py test analytics -k test_study
```

Tests cover paired one-variable configuration, run counts, display preparation,
malformed display inputs, null spread, preserved individual rows, repeated
analysis byte equality and absence of simulation calls on the analysis path.

## Final portfolio execution

The full curated study was executed once on 2026-09-13 with the existing Windows/MSVC Debug runtime. It completed all 300 runs in **3005.598 seconds (50 minutes 5.598 seconds)**, including sequential ingestion, evaluation and analysis. This is end-to-end elapsed time, not simulation-only throughput.

The 300 individual rows and 240 distinct run configurations reconcile with all aggregate tables. Every condition has 20 valid runs for the displayed metrics. Reanalysis from the saved sweeps produced 76 byte-identical files, without executing simulation.

| Dimension / conditions | Primary result: mean +/- sample SD |
| --- | --- |
| Sensor noise: 0 / 1 / 3 | Tracking RMSE: 0.2130 +/- 0.0255 / 1.1502 +/- 0.0161 / 2.8774 +/- 0.0261 m |
| Detection reliability: 0.5 / 0.75 / 1 | Measurement yield: 274.7000 +/- 2.1300 / 390.0500 +/- 2.3946 / 522.2000 +/- 3.0018 measurements/run |
| Clutter: 0 / 4 / 12 | False track samples: 0.0000 +/- 0.0000 / 0.8500 +/- 2.3005 / 35.3000 +/- 3.5851 track-samples/run |
| Target convergence: 0 / 0.5 / 1 | ID switches: 0.0000 +/- 0.0000 / 0.6000 +/- 1.4654 / 0.2000 +/- 0.8944 switches/run |
| Sensor network: 1 / 2 / 3 | Tracking RMSE: 1.7605 +/- 0.0266 / 1.4971 +/- 0.0269 / 1.1502 +/- 0.0161 m |

Notable relationships in this experiment:

- At noise 3, mean missed target samples increased to 44.85/run and ID switches to 4.7/run. Zero sensor noise still produced 0.2130 m tracking RMSE; noise-free measurements did not imply perfect tracking.
- Higher reliability produced more measurements and lower mean RMSE (1.4776 -> 1.2312 -> 1.1502 m); mean misses were 19.75 -> 8.8 -> 6/run.
- Clutter increased false-track samples strongly, but matched RMSE barely changed (1.1502 -> 1.1513 -> 1.1560 m). These metrics describe different aspects of tracking quality.
- Convergence was non-monotonic in ID switches: 0 -> 0.6 -> 0.2/run. The middle and high conditions had wide seed variation; no significance claim is made.
- Increasing sensor count was associated with lower RMSE and higher measurement yield (275.25 -> 358.8 -> 522.2 measurements/run). Geometry and cadence composition also changed.

The generator's existing coverage floor can depend on target-motion parameters, including convergence. Fixed configuration multipliers do not imply identical effective sensor ranges across all dimension studies. See retained sensor metadata; these are controlled procedural comparisons, not isolated physical causal estimates.

The overview and detail screens were launched against these persisted results and visually inspected. The verified README screenshot is an unedited application capture, not an illustrative mockup.
