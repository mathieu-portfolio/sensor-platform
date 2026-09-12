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

## Incremental raw-to-clean ingestion

Use `ingest` for a recording file or a nonrecursive inbox directory of `*.events`
files. The existing `export` command remains available for a direct clean export.

```sh
python scripts/dev.py analytics ingest recordings/ data/history
python scripts/dev.py analytics query data/history/clean --sql analytics/sql/sensor_summary.sql
```

Use global `--build-dir <existing-build>` before `analytics` if needed. The dev
wrapper supplies the runtime path; direct `python -m analytics ingest` requires
`--runtime <sensor_platform>`. Input files are visited in sorted filename order.
An empty inbox is a no-op. Results are JSON with per-recording status and counts
of new runs, new recordings and unchanged imports.

```text
data/history/
  raw/
    sha256=<original-byte-hash>/
      source.events
      manifest.json
      quality.json
  clean/
    run_id=42/
      events.parquet
      scans.parquet
      measurements.parquet
      manifest.json
```

Raw stores the exact snapshotted source bytes, including line endings, numeric
spelling and identical duplicate events. Archival happens before validation,
including for malformed or conflicting recordings. Validation uses the existing
normalization/duplicate policy and C++ replay validator. Thus raw
files containing repeated events may need normalization before direct replay.
Raw manifests record original SHA-256, normalized-stream SHA-256, run ID, first
source filename and duplicate count. Filenames/paths are not import identities:
renaming a byte-identical recording remains a no-op.

Known byte hashes verify the archived bytes and corresponding clean partition,
then skip parsing, runtime validation and Parquet conversion. New byte hashes are
validated; only absent clean runs are materialized. Equivalent logical streams
with different bytes receive separate raw archives but share the unchanged clean
run. Conflicting event payloads or different normalized streams under an existing
run ID are rejected after archival; no existing clean data is overwritten. Existing clean
partitions are never rebuilt to add another run. Checksums still require reading
the selected files; this is not a timestamp-only file discovery cache.

Run one importer per dataset. Each raw directory and each clean run is published
with its own staging-directory rename; the two layers and an entire inbox batch
are not one transaction. Raw publishes first. If conversion stops afterward,
retrying the source rebuilds only that missing clean run from archived bytes.
Earlier successful inbox entries remain imported when a later entry fails.
Integrity failures are reported rather than overwritten; there is no power-loss
durability or concurrent-writer guarantee. No mutable central registry is needed:
the raw manifest, quality report and matching clean manifest identify a completed import.

### Ingestion quality gate

Each raw archive contains a compact version-1 `quality.json`, keyed by original
SHA-256. It records `status` (`pending`, `passed`, `rejected`, or retryable `error`),
`stage`, and, after source validation, run ID, normalized SHA-256, duplicate count,
passed checks and source event/scan/measurement counts. Successful reports also
contain reconciled clean counts. Failures retain the exception type and diagnostic
in `error_type` and `error`, including parser line numbers or replay diagnostics.
Validation stops at the first failure; it does not enumerate every defect.

The gate enforces a complete single nonzero run lifecycle, contiguous global
sequences starting at one, valid run/sensor generation transitions, initialized
sensors and contiguous scan sequences per sensor generation. Times must be finite,
nonnegative and nondecreasing within each run generation; run resets restart time
at zero. Detection identities must be contiguous per sensor generation, values
must satisfy the recording contract, and declared measurement counts must match
the encoded tuples. Identical typed event duplicates are counted and removed;
conflicting identities fail. These rules remain authoritative in the replay validator.

Before the staging directory is published, ingestion reads the actual Parquet
files and compares all three row counts against the validated source, checks
event-to-scan counts and checks measurement counts for every scan (including empty
scans). Reimports verify file hashes and reconcile counts again. A successful
byte-identical reimport leaves the files and quality report unchanged.

Quarantine is logical: rejected bytes and their report stay under `raw/`; no new
`clean/run_id=...` partition is published. Existing valid runs are preserved when
a conflicting recording is rejected. The CLI raises an error and stops the inbox
batch at that recording. Repeating a rejected byte hash returns the saved failure.
Infrastructure failures are recorded as `error` and can be retried. Reports are
replaced atomically as processing advances; they are not an attempt history.
Archives created before quality reports existed are validated on their next import.

This gate checks recording structure and clean row consistency, not physical
plausibility, expected sensor coverage/rate, clock accuracy, or statistical drift.
Count reconciliation is not a field-by-field comparison of every Parquet value.

Queries continue to use the same tables and SQL; point them explicitly at `clean/`.
Existing direct-export datasets are not moved or migrated automatically.
Focused tests: `python scripts/dev.py test analytics -k IngestionTests`.

## Clean layout and schema

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

This is the direct-export layout; incremental ingestion uses the identical
partition structure under `data/history/clean/`.

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

Both local and Kafka recording/replay paths remain unchanged. The ingestion
quality gate is implemented above; the [demo](demo.md) exercises it end to end.
Next: larger multi-run fixtures and retention checks before adding continuous
Parquet batching or more storage systems.

DuckDB references: [Parquet read/write](https://duckdb.org/docs/stable/data/parquet/overview),
[Python client](https://duckdb.org/docs/stable/clients/python/overview).
