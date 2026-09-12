"""Curated local demo: orchestrate existing runtime and analytics implementations."""
import argparse
import csv
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = 42
SCENARIO = "default-three-radar-sample"


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def query_summary(connection, sql, destination):
    result = connection.execute(sql.read_text(encoding="utf-8"))
    columns = [column[0] for column in result.description]
    rows = result.fetchall()
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)
    return [dict(zip(columns, row)) for row in rows]


def viewer_command(arguments):
    if os.name == "nt":
        return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
    return shlex.join(arguments)


def run_demo(runtime, output, viewer):
    runtime, output, viewer = Path(runtime).resolve(), Path(output).resolve(), Path(viewer).resolve()
    output.mkdir(parents=True, exist_ok=True)
    summary = dict(schema_version=1, status="running", run_id=RUN_ID, scenario=SCENARIO,
                   stage="preflight", stage_seconds={})
    report_path = output / "summary.json"
    write_json(report_path, summary)
    env = {key.upper(): value for key, value in os.environ.items()} if os.name == "nt" else os.environ.copy()
    recording = output / "recording.events"
    replay = output / "replayed.events"
    tracks = output / "tracks.jsonl"
    metrics = output / "production.csv"

    def stage(name, operation):
        summary["stage"] = name
        write_json(report_path, summary)
        started = time.perf_counter()
        result = operation()
        summary["stage_seconds"][name] = round(time.perf_counter() - started, 6)
        return result

    try:
        if not runtime.is_file():
            raise FileNotFoundError(f"Build sensor_platform first; runtime missing: {runtime}")
        # Use the existing decoder, quality gate, immutable dataset reader and SQL.
        from analytics.dataset import SQL_DIR, open_dataset
        from analytics.events import read_unique
        from analytics.ingestion import ingest
        from analytics.track_events import load_frames, open_tracks

        with (output / "workflow.log").open("w", encoding="utf-8") as log:
            def execute(arguments, stdout=subprocess.DEVNULL):
                log.write("+ " + shlex.join([str(runtime), *map(str, arguments)]) + "\n")
                log.flush()
                subprocess.run([str(runtime), *map(str, arguments)], cwd=ROOT, env=env,
                               stdout=stdout, stderr=log, check=True, timeout=120)

            stage("record", lambda: execute(["run", "--run-id", str(RUN_ID), "--record", recording,
                                               "--sample-seconds", "20", "--metrics", metrics]))
            with replay.open("wb") as stream:
                stage("replay", lambda: execute(["replay", recording], stdout=stream))
            original_events, _, normalized_hash, _ = read_unique(recording)
            replay_events, _, replay_hash, _ = read_unique(replay)
            if original_events != replay_events or normalized_hash != replay_hash:
                raise ValueError("Replay does not match the recorded source")
            summary["replay"] = dict(status="matched", normalized_sha256=normalized_hash)
            stage("fusion", lambda: execute(["fuse", replay, "--output", tracks]))

        ingestion = stage("ingestion", lambda: ingest(recording, output / "dataset", runtime))
        write_json(output / "ingestion.json", ingestion)
        receipt = ingestion["imports"][0]
        quality_path = output / "dataset/raw" / ("sha256=" + receipt["recording_sha256"]) / "quality.json"
        quality = json.loads(quality_path.read_text(encoding="utf-8"))
        if quality["status"] != "passed":
            raise ValueError("Ingestion quality gate did not pass")
        summary["counts"] = receipt["rows"]
        summary["ingestion"] = dict(status=receipt["status"], quality_status=quality["status"],
                                    quality_report=quality_path.relative_to(output).as_posix(),
                                    checks_passed=quality["checks_passed"],
                                    recording_sha256=receipt["recording_sha256"])

        def analytics():
            with open_dataset(output / "dataset/clean") as connection:
                summary["runs"] = query_summary(connection, SQL_DIR / "run_summary.sql", output / "runs.csv")
                summary["sensors"] = query_summary(connection, SQL_DIR / "sensor_summary.sql", output / "sensors.csv")
            with open_tracks(tracks) as connection:
                track_summary = query_summary(connection, SQL_DIR / "fusion/summary.sql", output / "fusion.csv")
            frames = load_frames(tracks)
            if len(frames) != len(original_events) or any(
                    frame["run_id"] != event.run_id or frame["source_sequence"] != event.sequence
                    for frame, event in zip(frames, original_events)):
                raise ValueError("Fusion output does not correspond to the source run")
            summary["fusion"] = dict(config=frames[0]["config"], snapshots=len(frames),
                                     tracks_created=len({track["track_id"] for frame in frames for track in frame["tracks"]}),
                                     final_active_tracks=len(frames[-1]["tracks"]),
                                     associations=sum(len(frame["associations"]) for frame in frames),
                                     retirements=sum(len(frame["retired"]) for frame in frames),
                                     tracks=track_summary)
        stage("analytics", analytics)

        def prepare_viewer():
            shutil.copyfile(ROOT / "docs/sample.sensors.layout", output / "sensors.layout")
            arguments = [str(viewer), str(recording), "--layout", str(output / "sensors.layout")]
            summary["viewer"] = dict(available=viewer.is_file(), argv=arguments, truth="hidden",
                                     layout="sensors.layout", recording="recording.events")
            (output / "viewer.md").write_text(
                "# View the demo\n\n" +
                ("Viewer executable is available.\n" if viewer.is_file() else
                 "Build the optional sensor_platform_viewer target first (see docs/viewer.md).\n") +
                "\n```" + ("powershell" if os.name == "nt" else "sh") + "\n" +
                viewer_command(arguments) + "\n```\n\nPlayback starts at 1x. Space pauses, Left/Right step backward/forward (also after completion),\n"
                "R restarts, +/- changes speed, F fits; wheel zooms and left drag pans.\n"
                "Uses the same recording and default fusion configuration. Truth is hidden.\n",
                encoding="utf-8")
        stage("viewer", prepare_viewer)
        with metrics.open(newline="", encoding="utf-8") as stream:
            marks = list(csv.DictReader(stream))
        produced = [int(mark["wall_ns"]) for mark in marks if mark["phase"] == "produced"]
        summary["system"] = dict(recording_bytes=recording.stat().st_size,
                                 clean_parquet_bytes=sum(path.stat().st_size for path in (output / "dataset/clean").glob("run_id=*/*.parquet")),
                                 production_marks=len(produced),
                                 production_wall_span_ms=(produced[-1]-produced[0])/1e6 if produced else None,
                                 timing_note="Wall-clock production span includes recording/IO; stage durations are host-dependent, not benchmarks.")
        summary.update(status="passed", stage="complete")
        write_json(report_path, summary)
        return summary
    except Exception as error:
        summary.update(status="failed", error=str(error), error_type=type(error).__name__)
        write_json(report_path, summary)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--viewer", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "demo/results")
    args = parser.parse_args(argv)
    try:
        summary = run_demo(args.runtime, args.output, args.viewer)
        print(json.dumps(dict(status=summary["status"], run_id=summary["run_id"], counts=summary["counts"],
                              active_tracks=summary["fusion"]["final_active_tracks"],
                              ingestion=summary["ingestion"]["status"], quality=summary["ingestion"]["quality_status"],
                              summary=str(args.output.resolve() / "summary.json")), sort_keys=True))
    except Exception as error:
        print(f"demo: {error}; see summary.json and workflow.log under {args.output}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
