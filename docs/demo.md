# Curated end-to-end demo

From sensor-platform, with the existing runtime built and DuckDB installed in
`.venv` (see [analytics setup](analytics.md)), run:

```sh
python scripts/dev.py --build-dir build/consumer-verified demo
```

This is the single demo command. Use your actual build directory; build first with
`python scripts/dev.py --build-dir build/consumer-verified build --target sensor_platform`
if necessary. It never installs dependencies, silently builds, starts Kafka or
opens a graphical window. The wrapper selects `.venv` automatically. The optional
viewer may be built separately following [viewer setup](viewer.md).

The workflow generates four targets and three radars from a versioned procedural
configuration: target seed 2026, sensor-layout seed 73, duration 20 seconds, run ID
43. It records the existing typed events, captures production metrics, replays
and compares normalized events, runs default platform fusion, and ingests the
recording through the raw/clean quality gate. Existing run, sensor and fusion SQL
queries produce summaries for this run. The runtime writes the display-only
sensor layout from the same generated network it simulates. Event, recording,
fusion and analytics contracts are unchanged; the viewer owns no simulation.

Override generator parameters through the demo command:

```sh
python scripts/dev.py demo --scenario-seed 17 --sensor-layout-seed 73 --duration 30 --target-count 5 --sensor-count 4 --output build/demo-17
```

Changing only `--scenario-seed` preserves the entire sensor network, including
its measurement seeds and quality. Changing only `--sensor-layout-seed` preserves
target trajectories. Use a separate output directory for a different configuration
because the demo uses a fixed run identity. See [procedural scenarios](procedural-scenarios.md)
for generation rules, bounds and the reusable C++/runtime configuration API.

## Outputs

Everything generated is under the ignored `demo/results/` directory by default:

| Artifact | Contents |
| --- | --- |
| `summary.json` | Status/stage, scenario/run identity, source counts, fusion metrics, quality status/report path, viewer arguments, byte sizes and stage durations |
| `recording.events` | Deterministic original multi-radar recording |
| `scenario.config` | Versioned procedural configuration used by the runtime |
| `replayed.events` | Existing replay command's output, checked against the original |
| `tracks.jsonl` | Existing default fusion snapshots and associations |
| `production.csv` | Existing runtime `phase,sequence,wall_ns` observations |
| `ingestion.json` | Existing ingestion result, including imported/unchanged status |
| `dataset/raw/sha256=<hash>/` | Exact source bytes, manifest and `quality.json` |
| `dataset/clean/run_id=43/` | Events/scans/measurements Parquet files and manifest |
| `runs.csv`, `sensors.csv`, `fusion.csv` | Existing SQL summaries |
| `sensors.layout`, `viewer.md` | Generated sensor geometry and exact graphical viewer command |
| `workflow.log` | Runtime commands and their stderr diagnostics |

Read `summary.json` for the outcome, then view the prepared recording with:

```sh
python scripts/dev.py --build-dir build/consumer-verified viewer demo/results/recording.events --layout demo/results/sensors.layout
```

The viewer reuses default fusion just as the demo does;
it does not load the precomputed JSONL. Ground truth is not included or displayed.
No viewer binary is needed to produce the demo artifacts; its availability is
reported in the summary.

## Representative results and repeatability

The default procedural configuration produces 148 events, 143 scans and 522
measurements with the validated Windows Debug build. Sensor scan counts are
81/21/41 (4/1/2 Hz) and measurement counts 275/83/164. Fusion produces 148
source-event snapshots, 522 associations and 4 active tracks at the end. Quality
status is `passed`, with source and clean counts reconciled. Targets approach from
different directions, converge through the central overlap, then separate; the
mix includes straight, bowed-arc, zigzag and speed-burst motion. The precise
fusion details are in `fusion.csv` and `summary.json` and do not claim accuracy
against ground truth. False returns may create extra temporary tracks.

Re-running the command in the same directory regenerates deterministic recordings
and fusion outputs and returns ingestion status `unchanged`; existing raw/clean
files remain untouched. Determinism applies to the same build/toolchain, not
cross-platform random-number implementation equivalence. Wall-clock production
metrics and measured stage durations vary by host/run and are not benchmarks.
Production span includes recording and I/O, not just simulation work.

Use `demo --output <dedicated-directory>` for a separate result set. Keep one
writer per results directory. The workflow refreshes its named artifacts, retains
the immutable dataset, and never recursively deletes outputs. On failure it exits
nonzero and marks `summary.json` failed with the stage/error; already written files
remain available for diagnosis. Partial files or older artifacts are not proof of
success: check the summary status. A changed build/configuration producing different
events for run 43 is rejected by existing ingestion identity checks; use a new
output directory. The previous run-42 sample can coexist in the immutable dataset;
current demo summaries select run 43, leaving the old dataset intact.

Focused validation (build explicitly before tests):

```sh
python scripts/dev.py build
python scripts/dev.py test unit -R "platform_(procedural|multi_sensor_runner|events_and_replay|viewer_state|fusion)$"
python scripts/dev.py test workflow
```

The focused tests cover generated-world observability and convergence, motion
behaviors, seed isolation, byte-identical recordings, matching viewer geometry,
real pipeline repeat ingestion, CLI routing/validation and failure handling.
No Kafka or sandbox-app suite is needed for this platform-only implementation.
