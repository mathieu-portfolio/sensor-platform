"""Immutable, per-run Parquet materialization and DuckDB views."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import duckdb

from .events import read_unique
from .quality import reconcile, source_counts

SQL_DIR = Path(__file__).resolve().parent / "sql"
TABLES = ("events", "scans", "measurements")
SCHEMA_VERSION = 1


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_partition(partition):
    manifest = json.loads((partition / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported dataset schema: {partition}")
    if partition.name != f"run_id={manifest['run_id']}":
        raise ValueError("partition/run identity mismatch")
    for table in TABLES:
        if digest(partition / f"{table}.parquet") != manifest["files"][table]:
            raise ValueError(f"dataset file integrity check failed: {partition}/{table}.parquet")
    reconcile(partition, manifest["rows"])
    return manifest


def validate_recording(source, runtime):
    source, runtime = Path(source), Path(runtime).resolve()
    events, normalized, source_hash, duplicates = read_unique(source)
    # Use the existing authoritative lifecycle/order validator, not a second Python implementation.
    # This happens before creating or changing a dataset.
    with tempfile.TemporaryDirectory(prefix="sensor-validate-") as temporary:
        recording = Path(temporary) / "deduplicated.events"
        recording.write_text(normalized, encoding="ascii", newline="\n")
        env = {key.upper(): value for key, value in os.environ.items()} if os.name == "nt" else None
        result = subprocess.run([str(runtime), "replay", str(recording)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, timeout=60)
        if result.returncode:
            raise ValueError("runtime validation failed: " + result.stderr.decode(errors="replace").strip())
    return events, source_hash, duplicates


def export_run(source, dataset, runtime):
    events, source_hash, duplicates = validate_recording(source, runtime)
    return materialize_run(events, source_hash, duplicates, dataset)


def materialize_run(events, source_hash, duplicates, dataset):
    """Publish an already validated run using the existing immutable partition rules."""
    dataset = Path(dataset)
    run_id = events[0].run_id
    expected = source_counts(events)
    destination = dataset / f"run_id={run_id}"

    def existing():
        manifest = verify_partition(destination)
        if manifest["source_sha256"] != source_hash:
            raise ValueError(f"run {run_id} already exists with different events; assign a new run ID")
        reconcile(destination, expected)
        return {"status": "unchanged", "run_id": run_id, "duplicates_removed": duplicates,
                "rows": manifest["rows"]}

    if destination.exists():
        return existing()
    dataset.mkdir(parents=True, exist_ok=True)
    # All tables are completed in an ignored staging directory, then published by one rename.
    # A failed export never exposes a partial run_id partition.
    with tempfile.TemporaryDirectory(prefix=".ingest-", dir=dataset) as temporary:
        staging = Path(temporary)
        with duckdb.connect() as connection:
            connection.execute((SQL_DIR / "schema.sql").read_text())
            rows = {table: [] for table in TABLES}
            for event in events:
                event_row, scan_row, measurement_rows = event.rows()
                rows["events"].append(event_row)
                if scan_row is not None:
                    rows["scans"].append(scan_row)
                    rows["measurements"].extend(measurement_rows)
            for table in TABLES:
                if rows[table]:
                    placeholders = ",".join("?" for _ in rows[table][0])
                    connection.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows[table])
                connection.table(table).order("run_id, stream_sequence").write_parquet(
                    str(staging / f"{table}.parquet"), compression="zstd")
        actual = reconcile(staging, expected)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "recording_version": 1,
            "run_id": run_id,
            "source_sha256": source_hash,
            "rows": actual,
            "files": {table: digest(staging / f"{table}.parquet") for table in TABLES},
        }
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        try:
            staging.rename(destination)
        except OSError:
            # Concurrent identical imports can converge; conflicts never overwrite a run.
            if destination.exists():
                return existing()
            raise
    return {"status": "created", "run_id": run_id, "duplicates_removed": duplicates, "rows": manifest["rows"]}


def open_dataset(dataset):
    partitions = sorted(Path(dataset).glob("run_id=*"))
    if not partitions:
        raise ValueError("dataset contains no completed run partitions")
    for partition in partitions:
        verify_partition(partition)
    connection = duckdb.connect()
    try:
        for table in TABLES:
            # Keep UBIGINT run IDs stored in files; avoid Hive inference converting them to BIGINT.
            connection.read_parquet([str(p / f"{table}.parquet") for p in partitions],
                                    hive_partitioning=False).create_view(table)
    except Exception:
        connection.close()
        raise
    return connection
