"""python -m experiments run config.json output/ --bin-dir build/Debug [--transport kafka]."""
import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid

from .config import resolve, plan, simulation_float
from .metrics import read_events, read_trace, calculate


def write_csv(path, columns, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)


def run(args):
    config = resolve(json.loads(args.config.read_text()))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)  # Evidence is never overwritten.
    (output / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    (output / "runtime.plan").write_text(plan(config), encoding="ascii")
    reference_plan = output / "reference.plan"
    reference_plan.write_text(plan(config, paced=False), encoding="ascii")
    suffix = ".exe" if os.name == "nt" else ""
    runtime = str(args.bin_dir.resolve() / ("sensor_platform" + suffix))
    kafka = str(args.bin_dir.resolve() / ("sensor_platform_kafka" + suffix))
    env = {k.upper(): v for k, v in os.environ.items()} if os.name == "nt" else None
    popen_options = dict(env=env)
    if os.name == "nt":
        popen_options["creationflags"] = subprocess.CREATE_NO_WINDOW
    start = datetime.now(timezone.utc).isoformat()
    errors = []
    topic = None
    processes = []
    returncodes = {}
    try:
        with (output / "expected.events").open("wb") as stream:
            subprocess.run([runtime, "run", "--run-id", str(config["run_id"]), "--experiment", str(reference_plan)],
                           stdout=stream, stderr=subprocess.PIPE, check=True, timeout=args.timeout, **popen_options)
        producer = [runtime, "run"]
        consumer = [runtime, "observe"]
        if args.transport == "kafka":
            topic = "sensor-experiment-" + uuid.uuid4().hex[:12]
            if args.kafka_home:
                admin = [args.java, "-cp", str(args.kafka_home.resolve() / "libs" / "*"),
                         "org.apache.kafka.tools.TopicCommand", "--bootstrap-server", args.brokers]
            else:
                admin = ["docker", "compose", "exec", "-T", "kafka", "/opt/kafka/bin/kafka-topics.sh",
                         "--bootstrap-server", "localhost:19092"]
            subprocess.run(admin + ["--create", "--topic", topic, "--partitions", "1", "--replication-factor", "1"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=args.timeout, **popen_options)
            common = ["--brokers", args.brokers, "--topic", topic, "--timeout-ms", "90000"]
            producer = [kafka, "producer", *common]
            consumer = [kafka, "consumer", *common, "--group", topic + "-viewer"]
        producer += ["--run-id", str(config["run_id"]), "--experiment", str(output / "runtime.plan"),
                     "--metrics", str(output / "produced.csv")]
        consumer += ["--metrics", str(output / "consumed.csv")]
        for field, option in [("consumer_delay_ms", "--delay-ms"), ("pause_after_events", "--pause-after"), ("pause_ms", "--pause-ms")]:
            if config[field]:
                consumer += [option, str(config[field])]
        (output / "commands.json").write_text(json.dumps(dict(producer=producer, consumer=consumer), indent=2))
        with (output / "producer.stderr").open("wb") as pe, (output / "consumer.stderr").open("wb") as ce, (output / "received.events").open("wb") as received:
            p = subprocess.Popen(producer, stdout=subprocess.PIPE if args.transport == "local" else subprocess.DEVNULL,
                                 stderr=pe, **popen_options)
            processes.append(p)
            time.sleep(config["consumer_start_delay_ms"] / 1000)
            c = subprocess.Popen(consumer, stdin=p.stdout if args.transport == "local" else subprocess.DEVNULL,
                                 stdout=received, stderr=ce, **popen_options)
            processes.append(c)
            if p.stdout:
                p.stdout.close()
            deadline = time.monotonic() + args.timeout
            for name, process in [("producer", p), ("consumer", c)]:
                returncodes[name] = process.wait(timeout=max(0.01, deadline-time.monotonic()))
                if returncodes[name]:
                    errors.append(f"{name} exited {returncodes[name]}; see {name}.stderr")
        # Same complete-file lifecycle validation as historical ingestion/replay.
        result = subprocess.run([runtime, "replay", str(output / "received.events")], stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, timeout=args.timeout, **popen_options)
        if result.returncode:
            errors.append(result.stderr.decode(errors="replace").strip())
    except (OSError, subprocess.SubprocessError) as error:
        errors.append(str(error))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.wait()
    expected, expected_errors = read_events(output / "expected.events")
    actual, actual_errors = read_events(output / "received.events")
    errors += expected_errors + actual_errors
    metrics, latency, backlog = calculate(read_trace(output / "produced.csv"), read_trace(output / "consumed.csv"), expected, actual)
    if config["pause_ms"] and (not metrics["pause_observed"] or metrics["catchup_seconds"] is None):
        errors.append("configured consumer pause did not occur or consumer never caught up")
    sensor_stats = {}
    for event in actual:
        if event.kind == "MEASUREMENTS":
            row = sensor_stats.setdefault(str(event.sensor_id), dict(scans=0, detections=0, outage_scans=0))
            row["scans"] += 1
            row["detections"] += len(event.detections)
            outage = config["outage"]
            if outage and event.sensor_id == outage["sensor_id"] and simulation_float(outage["start"]) <= event.time < simulation_float(outage["end"]):
                row["outage_scans"] += 1
    if any(s["outage_scans"] for s in sensor_stats.values()):
        errors.append("sensor emitted during configured outage")
    metrics["integrity_pass"] &= not errors and bool(expected)
    summary = dict(config=config, transport=args.transport, topic=topic, started_utc=start,
                   finished_utc=datetime.now(timezone.utc).isoformat(), environment=platform.platform(),
                   metrics=metrics, per_sensor=sensor_stats, errors=errors, process_returncodes=returncodes)
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_csv(output / "latency.csv", ["sequence", "produced_wall_ns", "consumed_wall_ns", "latency_ms"], latency)
    write_csv(output / "backlog.csv", ["wall_ns", "outstanding_events"], backlog)
    print(json.dumps(summary, indent=2))
    return 0 if metrics["integrity_pass"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    experiment = sub.add_parser("run")
    experiment.add_argument("config", type=Path)
    experiment.add_argument("output", type=Path)
    experiment.add_argument("--bin-dir", type=Path, required=True)
    experiment.add_argument("--transport", choices=["local", "kafka"], default="local")
    experiment.add_argument("--brokers", default="localhost:9092")
    experiment.add_argument("--kafka-home", type=Path)
    experiment.add_argument("--java", default="java")
    experiment.add_argument("--timeout", type=float, default=180)
    report = sub.add_parser("report")
    report.add_argument("results", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "run":
            return run(args)
        import duckdb
        files = [str(p) for p in args.results.glob("*/summary.json")]
        if not files:
            raise ValueError("no experiment summaries found")
        with duckdb.connect() as db:
            db.read_json(files).create_view("experiments")
            result = db.execute((Path(__file__).parent / "sql/comparison.sql").read_text())
            writer = csv.writer(sys.stdout, lineterminator="\n")
            writer.writerow(c[0] for c in result.description)
            writer.writerows(result.fetchall())
        return 0
    except Exception as error:
        print(f"experiments: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
