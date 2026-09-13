"""Explicit offline evaluation model; production dataset readers never load truth."""
import json
from pathlib import Path

from .dataset import digest, open_dataset, verify_partition
from .publication import staging_directory
from .track_events import load_frames, open_tracks
from evaluation.metrics import evaluate

SCHEMAS = {
    "runs": "run_id UBIGINT, generator_version VARCHAR, scenario_seed UINTEGER, layout_seed UINTEGER, duration_seconds INTEGER, target_count INTEGER, sensor_count INTEGER, tick_hz INTEGER, speed_min DOUBLE, speed_max DOUBLE, maneuver DOUBLE, convergence DOUBLE, spawn_spread DOUBLE, coverage DOUBLE, layout_spread DOUBLE, noise DOUBLE, reliability DOUBLE, clutter DOUBLE",
    "sensors": "run_id UBIGINT, sensor_id INTEGER, seed UINTEGER, x DOUBLE, y DOUBLE, heading_radians DOUBLE, field_of_view_radians DOUBLE, range DOUBLE, refresh_rate_hz DOUBLE, range_noise DOUBLE, detection_probability DOUBLE, false_positive_rate_hz DOUBLE",
    "ground_truth": "run_id UBIGINT, target_id INTEGER, timestamp DOUBLE, x DOUBLE, y DOUBLE, vx DOUBLE, vy DOUBLE, motion_type VARCHAR",
}
TABLES = (*SCHEMAS, "tracks", "run_metrics")


def verify_analysis(partition, clean):
    manifest = json.loads((partition / "manifest.json").read_text())
    if manifest.get("schema_version") != 1 or partition.name != f"run_id={manifest['run_id']}":
        raise ValueError("invalid analytical partition identity/version")
    source = verify_partition(clean / partition.name)
    if source["source_sha256"] != manifest["source_sha256"]:
        raise ValueError("analytical/clean source mismatch")
    for table in TABLES:
        if digest(partition / f"{table}.parquet") != manifest["files"][table]:
            raise ValueError("analytical file integrity check failed")
    return manifest


def export_analysis(artifacts, tracks, dataset, gate=5):
    """Publish one complete procedural run, bound to its immutable clean recording.

    Truth covers every simulation tick. Evaluation uses the last MEASUREMENTS
    frame at each acquisition time, avoiding overlapping-sensor weighting.
    """
    artifacts, tracks, dataset = Path(artifacts), Path(tracks), Path(dataset)
    frames = load_frames(tracks)
    run_id = frames[0]["run_id"]
    source = verify_partition(dataset / "clean" / f"run_id={run_id}")
    inputs = {name: digest(artifacts / f"{name}.csv") for name in SCHEMAS}
    inputs["tracks"] = digest(tracks)
    inputs["evaluation_gate"] = gate
    parent = dataset / "analysis"
    destination = parent / f"run_id={run_id}"

    def existing():
        manifest = verify_analysis(destination, dataset / "clean")
        if manifest["inputs"] != inputs:
            raise ValueError("run already has different analytical artifacts; assign a new run ID")
        return manifest

    if destination.exists():
        return existing()
    parent.mkdir(parents=True, exist_ok=True)
    with staging_directory(parent) as staging, open_dataset(dataset / "clean") as db:
        for table, schema in SCHEMAS.items():
            db.execute(f"CREATE TABLE {table} ({schema})")
            columns = dict(column.strip().split() for column in schema.split(","))
            data = db.read_csv(str(artifacts / f"{table}.csv"), header=True, columns=columns)
            data.insert_into(table)
            if db.execute(f"SELECT count(*) FROM {table} WHERE run_id != ? OR run_id IS NULL", [run_id]).fetchone()[0]:
                raise ValueError("analytical run identity mismatch")
            if db.execute(f"SELECT count(*) FROM {table} WHERE " + " OR ".join(f"{c} IS NULL" for c in columns)).fetchone()[0]:
                raise ValueError("null analytical value")
            numeric = [c for c, t in columns.items() if t == "DOUBLE"]
            if numeric and db.execute(f"SELECT count(*) FROM {table} WHERE " + " OR ".join(f"NOT isfinite({c})" for c in numeric)).fetchone()[0]:
                raise ValueError("nonfinite analytical value")
        metadata = db.execute("SELECT duration_seconds,target_count,sensor_count,tick_hz FROM runs").fetchall()
        if len(metadata) != 1:
            raise ValueError("expected one run metadata row")
        duration, targets, sensors, hz = metadata[0]
        if duration <= 0 or targets <= 0 or sensors <= 0 or hz != 8:
            raise ValueError("invalid procedural metadata")
        if db.execute("SELECT count(*),count(DISTINCT sensor_id) FROM sensors").fetchone() != (sensors, sensors):
            raise ValueError("sensor count/identity mismatch")
        starts = db.execute("SELECT sensor_id,seed FROM events WHERE run_id=? AND event_type='SENSOR_STARTED' ORDER BY sensor_id", [run_id]).fetchall()
        if starts != db.execute("SELECT sensor_id,seed FROM sensors ORDER BY sensor_id").fetchall():
            raise ValueError("sensor metadata does not match recording")
        events = db.execute("SELECT stream_sequence,event_time_seconds,event_type,run_generation FROM events WHERE run_id=? ORDER BY stream_sequence", [run_id]).fetchall()
        if events != [(f["source_sequence"], f["acquisition_time"], f["source_type"], f["run_generation"]) for f in frames]:
            raise ValueError("track frames do not match recording")
        if frames[-1]["acquisition_time"] != duration or any(f["run_generation"] != 0 for f in frames):
            raise ValueError("expected one complete procedural generation")
        truth_rows = db.execute("SELECT target_id,timestamp,x,y FROM ground_truth ORDER BY timestamp,target_id").fetchall()
        expected = {(target, tick / hz) for tick in range(duration * hz + 1) for target in range(1, targets + 1)}
        if len(truth_rows) != len(expected) or {(r[0], r[1]) for r in truth_rows} != expected:
            raise ValueError("truth target/tick grid mismatch")
        by_time = {}
        for target, time, x, y in truth_rows:
            by_time.setdefault(time, []).append(dict(truth_id=target, x=x, y=y))
        latest = {f["acquisition_time"]: f for f in frames if f["source_type"] == "MEASUREMENTS"}
        truth = [dict(run_id=run_id, run_generation=0, source_sequence=f["source_sequence"],
                      acquisition_time=time, entities=by_time[time]) for time, f in latest.items()]
        metrics = evaluate(frames, truth, gate)
        with open_tracks(tracks) as track_db:
            track_db.table("track_samples").order("run_id, run_generation, acquisition_time, track_id").write_parquet(str(staging / "tracks.parquet"), compression="zstd")
        metric_schema = ",".join(f"{key} {'DOUBLE' if key in ('position_rmse', 'mean_position_error', 'evaluation_gate') else 'UBIGINT'}" for key in metrics)
        db.execute(f"CREATE TABLE run_metrics (run_id UBIGINT, evaluator_version VARCHAR, fusion_config VARCHAR, {metric_schema})")
        values = [run_id, "greedy-distance-v1", json.dumps(frames[0]["config"], sort_keys=True), *metrics.values()]
        db.execute("INSERT INTO run_metrics VALUES (" + ",".join("?" for _ in values) + ")", values)
        for table in (*SCHEMAS, "run_metrics"):
            order = {"sensors": "sensor_id", "ground_truth": "timestamp,target_id"}.get(table, "run_id")
            db.table(table).order(order).write_parquet(str(staging / f"{table}.parquet"), compression="zstd")
        rows = {t: db.read_parquet(str(staging / f"{t}.parquet"), hive_partitioning=False).count("*").fetchone()[0] for t in TABLES}
        manifest = dict(schema_version=1, run_id=run_id, source_sha256=source["source_sha256"], inputs=inputs,
                        rows=rows, files={t: digest(staging / f"{t}.parquet") for t in TABLES})
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        try:
            staging.rename(destination)
        except OSError:
            if destination.exists():
                return existing()
            raise
    return manifest


def open_analysis(dataset):
    """Explicit opt-in reader combining clean events with offline evaluation tables."""
    dataset = Path(dataset)
    partitions = sorted((dataset / "analysis").glob("run_id=*"))
    if not partitions:
        raise ValueError("dataset contains no analytical partitions")
    for partition in partitions:
        verify_analysis(partition, dataset / "clean")
    db = open_dataset(dataset / "clean")
    try:
        for table in TABLES:
            db.read_parquet([str(p / f"{table}.parquet") for p in partitions], hive_partitioning=False).create_view(table)
        return db
    except Exception:
        db.close()
        raise
