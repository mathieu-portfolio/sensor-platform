"""Read completed truth-free global-track JSON Lines; no evaluation dependency."""
import json
import math


def load_frames(path):
    frames = [json.loads(line) for line in path.read_text().splitlines()]
    if not frames or frames[0]["source_type"] != "RUN_STARTED" or frames[-1]["source_type"] != "RUN_FINISHED":
        raise ValueError("incomplete global-track output")
    run, generation, last_time = frames[0]["run_id"], 0, 0
    for sequence, frame in enumerate(frames, 1):
        if frame["schema_version"] != 1 or frame["event_type"] != "GLOBAL_TRACKS" or frame["run_id"] != run or frame["source_sequence"] != sequence:
            raise ValueError("invalid global-track order/schema/run")
        if frame["source_type"] == "RUN_RESET":
            generation += 1
            last_time = 0
            if frame["acquisition_time"] != 0:
                raise ValueError("reset did not rewind time")
        time = frame["acquisition_time"]
        if frame["run_generation"] != generation or not math.isfinite(time) or time < last_time:
            raise ValueError("invalid global-track generation/time")
        last_time = time
        ids = set()
        for track in frame["tracks"]:
            if track["track_id"] in ids or track["track_id"] <= 0 or track["state"] not in ("tentative", "confirmed", "coasting"):
                raise ValueError("invalid track identity/state")
            ids.add(track["track_id"])
            if any(not math.isfinite(track[key]) for key in ("x", "y", "vx", "vy", "last_seen")):
                raise ValueError("nonfinite track state")
    return frames


def open_tracks(path):
    import duckdb
    frames = load_frames(path)
    db = duckdb.connect()
    try:
        db.execute("CREATE TABLE track_samples(run_id UBIGINT, run_generation UBIGINT, source_sequence UBIGINT, "
                   "acquisition_time DOUBLE, track_id UBIGINT, state VARCHAR, x DOUBLE, y DOUBLE, "
                   "vx DOUBLE, vy DOUBLE, last_seen DOUBLE, observations UBIGINT, sensor_count INTEGER)")
        # One final snapshot per timestamp, so overlapping sensors do not inflate track statistics.
        latest = {(f["run_id"], f["run_generation"], f["acquisition_time"]): f for f in frames}
        rows = [(f["run_id"], f["run_generation"], f["source_sequence"], f["acquisition_time"], t["track_id"],
                 t["state"], t["x"], t["y"], t["vx"], t["vy"], t["last_seen"], t["observations"], len(t["sensors"]))
                for f in latest.values() for t in f["tracks"]]
        if rows:
            db.executemany("INSERT INTO track_samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        return db
    except Exception:
        db.close()
        raise
