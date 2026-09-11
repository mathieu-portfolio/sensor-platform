# Historical Parquet analytics

The Python `analytics/` package consumes complete format-v1 recordings from either
the local runtime or Kafka recorder. DuckDB is the only third-party dependency;
it writes Parquet and executes SQL directly over the files. No Python packages
are needed to build or run the C++ runtime.

```text
simulation -> typed events -> local recording --+
                       +--> Kafka -> recorder --+-> historical export -> Parquet -> DuckDB/SQL
```

## Quick demonstration

From sensor-platform (Windows paths shown; on Unix use `.venv/bin/python` and
the single-config executable path):

```sh
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r analytics/requirements.txt
build/Debug/sensor_platform.exe run --run-id 42 --record build/sample.events
.venv/Scripts/python.exe -m analytics export build/sample.events data --runtime build/Debug/sensor_platform.exe
.venv/Scripts/python.exe -m analytics query data --sql analytics/sql/sensor_summary.sql
.venv/Scripts/python.exe -m analytics query data --sql analytics/sql/scan_cadence.sql
```

Use your actual build directory for `--runtime`. Export normalizes identical
duplicate events, then calls the existing C++ `replay` validator before touching
the dataset. Thus lifecycle, reset, sequence, timestamp and measurement rules
remain authoritative in the runtime. Replay stdout is discarded, not reparsed.
The Python layer decodes the documented numeric grammar into table rows.
Malformed/incomplete recordings fail before publishing a partition.

For Kafka, first run the existing recorder to completion, then export its
`.events` file using the same command. Direct continuous Kafka-to-Parquet
consumption is outside this milestone.

## Layout and schema

```text
data/
  run_id=42/
    events.parquet
    scans.parquet
    measurements.parquet
    manifest.json
  run_id=43/
    ...
```

One immutable directory per complete run; each contains three Zstandard-compressed
Parquet files, including schema-bearing zero-row files when necessary. Sensors
and reset generations remain columns, avoiding files for every scan or sensor.
This is a local batch layout for modest runs, not a streaming file-rotation scheme.

All three tables store `run_id`, `run_generation` and `stream_sequence` as
unsigned 64-bit integers. The remaining fields are:

| Table | Rows | Additional columns |
| --- | --- | --- |
| events | Every unique event, including lifecycle | event_time_seconds, event_type, nullable sensor_id, sensor_generation, scan_sequence, measurement_count, seed |
| scans | Every completed scan | acquisition_time_seconds, sensor_id, sensor_generation, scan_sequence, measurement_count |
| measurements | Every detection | acquisition_time_seconds, sensor_id, sensor_generation, scan_sequence, detection_id, x, y, confidence, uncertainty_radius |

Sensor/detection IDs are signed 32-bit integers, seed is unsigned 32-bit,
generations/sequences/counts are unsigned 64-bit, and numeric observations/times
are 32-bit FLOAT, matching the event contract. Times are elapsed simulation
seconds and positions retain sandbox world units. No evaluation truth is stored.
Full definitions and ingestion constraints are in `analytics/sql/schema.sql`.

An empty scan has a scan row with measurement_count=0 and zero measurement rows.
A not-due poll has no event or scan row. This distinction preserves empty-scan
rates and cadence. Lifecycle rows retain starts/resets/finish and seed metadata.

Each manifest records schema version 1, a normalized event-stream SHA-256,
table row counts and Parquet file hashes. Queries/import retries verify hashes.
New files are built in a staging directory, then published together by one
directory rename. Interrupted staging directories are not query inputs.
Published partitions are immutable; missing/corrupt files fail clearly.
Data is local, and large runs are currently batch-decoded in memory.

## Duplicate and conflict policy

Event key: `(run_id, stream_sequence)`. Within an input, repeated events with
identical typed payloads are removed; first-seen order is preserved. Float tokens
are normalized to the contract's float32 values. Different payloads under the
same key fail. Missing sequences and reordered first occurrences fail runtime
validation; ingestion never sorts away ordering errors.

Re-importing the same normalized complete run returns `unchanged`, preserving
all existing files. A different stream with the same run ID fails; use a new run
ID for an independent simulation. This includes conflicting sensor/reset metadata.
No upsert, partial-run append or exactly-once transport claim is made. Retried
Kafka recorder output can therefore be ingested without accumulating duplicate rows.

## Queries and verified example

The query command registers `events`, `scans`, and `measurements` DuckDB views
over complete partitions, then executes the selected version-controlled SQL:

- `sensor_summary.sql`: scans, detections, empty-scan percentage and yield,
  including started sensors with no scans.
- `scan_cadence.sql`: min/mean/max acquisition interval and observed Hz,
  partitioned by run, world generation, sensor and sensor generation.
- `run_summary.sql`: event count, sensor count, last recorded time, scans and detections per world generation.
- `detections_over_time.sql`: one-second buckets retaining empty scans.
- `event_counts.sql`: lifecycle and measurement event counts by type.
- `measurement_distribution.sql`: per-sensor volume/share, confidence,
  uncertainty and spatial extent from measurement rows.

Cadence never bridges resets. The last recorded timestamp is the observed duration
of a generation; for the final generation RUN_FINISHED records its end time.
A reset generation can have unobserved time after its last event, so this is not
an inferred wall-clock or exact physics runtime.

Actual SQL results for the unchanged three-radar sample, run 42 over [0,1] seconds:

| Sensor | Scans | Detections | Empty scans | Observed Hz |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2 | 2 | 0 | 1 |
| 2 | 3 | 3 | 0 | 2 |
| 3 | 5 | 6 | 0 | 4 |

Total: 15 events, 10 scans, 11 detections, last event time 1 second.
Sensor 3's volume includes a simulated false return, represented as a normal
measurement without exposing evaluation truth. Tests also use other runs,
nontrivial float values, empty scans, no-scan runs, sensor resets and world resets.

Run tests from the repository root, pointing at an existing runtime build:

```powershell
$env:SENSOR_PLATFORM_RUNTIME = 'build/Debug/sensor_platform.exe'
.venv/Scripts/python.exe -m unittest discover -s analytics/tests -v
```

Both local and Kafka recording/replay paths remain unchanged. Next: larger
multi-run fixtures and data-quality/retention checks before adding continuous
Parquet batching, more storage systems or analytics infrastructure.

DuckDB references: [Parquet read/write](https://duckdb.org/docs/stable/data/parquet/overview),
[Python client](https://duckdb.org/docs/stable/clients/python/overview).
