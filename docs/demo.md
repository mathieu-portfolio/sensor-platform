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

The workflow invokes the existing default `runSample` (run ID 42, seeds 11/22/33,
three radars at 1/2/4 Hz over simulation time 0–1 s), captures its existing production
metrics, replays and compares normalized events, runs default platform fusion, and
ingests the recording with the existing raw/clean quality gate. Existing run,
sensor and fusion SQL queries then produce summaries. Finally it copies the
sample's display-only sensor layout and writes a ready-to-use viewer command.
There are no new simulation, fusion, recording or analytics schemas.

## Outputs

Everything generated is under the ignored `demo/results/` directory by default:

| Artifact | Contents |
| --- | --- |
| `summary.json` | Status/stage, scenario/run identity, source counts, fusion metrics, quality status/report path, viewer arguments, byte sizes and stage durations |
| `recording.events` | Deterministic original multi-radar recording |
| `replayed.events` | Existing replay command's output, checked against the original |
| `tracks.jsonl` | Existing default fusion snapshots and associations |
| `production.csv` | Existing runtime `phase,sequence,wall_ns` observations |
| `ingestion.json` | Existing ingestion result, including imported/unchanged status |
| `dataset/raw/sha256=<hash>/` | Exact source bytes, manifest and `quality.json` |
| `dataset/clean/run_id=42/` | Events/scans/measurements Parquet files and manifest |
| `runs.csv`, `sensors.csv`, `fusion.csv` | Existing SQL summaries |
| `sensors.layout`, `viewer.md` | Sample sensor geometry and exact graphical viewer command |
| `workflow.log` | Runtime commands and their stderr diagnostics |

Read `summary.json` for the outcome, then run the command in `viewer.md` to view
the prepared recording. The viewer reuses default fusion just as the demo does;
it does not load the precomputed JSONL. Ground truth is not included or displayed.
No viewer binary is needed to produce the demo artifacts; its availability is
reported in the summary.

## Representative results and repeatability

The sample produces 15 events, 10 scans and 11 measurements. Sensor scan counts
are 2/3/5 and measurement counts 2/3/6. Fusion produces 15 source-event snapshots,
11 associations and 2 active tracks at the end. Quality status is `passed`, with
source and clean counts reconciled. The precise fusion details are in `fusion.csv`
and `summary.json` and do not claim accuracy against ground truth.

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
success: check the summary status. A changed build producing different events for
run 42 is rejected by existing ingestion identity checks; use a new output directory
for a different version of the sample.

Focused validation (build explicitly before tests):

```sh
python scripts/dev.py --build-dir build/consumer-verified test workflow
```

The demo tests cover the real pipeline and repeat ingestion, command routing/dry
run, subprocess failure and quality failure. No Kafka, core, fusion or analytics
test suites are required for this orchestration-only change.
