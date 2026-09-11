"""Real Kafka smoke test. Unit tests do not need Kafka; this script needs a running broker."""
import argparse
import os
from pathlib import Path
import subprocess
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--bin-dir", type=Path, required=True)
parser.add_argument("--brokers", default="localhost:9092")
parser.add_argument("--compose-file", type=Path, default=Path(__file__).resolve().parents[1] / "compose.yaml")
parser.add_argument("--kafka-home", type=Path, help="Optional native Kafka installation instead of Docker for topic admin")
parser.add_argument("--java", default="java")
args = parser.parse_args()
env = {key.upper(): value for key, value in os.environ.items()}
suffix = ".exe" if os.name == "nt" else ""
local = str(args.bin_dir.resolve() / ("sensor_platform" + suffix))
kafka = str(args.bin_dir.resolve() / ("sensor_platform_kafka" + suffix))
topic = "sensor-integration-" + uuid.uuid4().hex[:12]
output_dir = args.bin_dir.resolve() / topic
output_dir.mkdir()

def run(command, success=True):
    result = subprocess.run(command, capture_output=True, env=env, timeout=90)
    if (result.returncode == 0) != success:
        raise RuntimeError(f"{command}: exit {result.returncode}\n{result.stderr.decode(errors='replace')}")
    return result.stdout.replace(b"\r\n", b"\n")

if args.kafka_home:
    admin = [args.java, "-cp", str(args.kafka_home.resolve() / "libs" / "*"), "org.apache.kafka.tools.TopicCommand",
             "--bootstrap-server", args.brokers]
else:
    admin = ["docker", "compose", "-f", str(args.compose_file), "exec", "-T", "kafka",
             "/opt/kafka/bin/kafka-topics.sh", "--bootstrap-server", "localhost:19092"]
run(admin + ["--create", "--topic", topic, "--partitions", "1", "--replication-factor", "1"])
common = ["--brokers", args.brokers, "--topic", topic]
expected = run([local, "run", "--run-id", "42"])
(output_dir / "live.events").write_bytes(expected)

# No downstream process exists yet: Kafka must retain the producer's completed run.
run([kafka, "producer", *common, "--run-id", "42"])
received = run([kafka, "consumer", *common, "--group", topic + "-viewer"])
assert received == expected, "queued viewer stream differs"
(output_dir / "viewer.events").write_bytes(received)
recording = output_dir / "recorded.events"
run([kafka, "recorder", *common, "--group", topic + "-recorder", "--output", str(recording)])
assert recording.read_bytes() == expected, "incremental recorder differs"
replayed = run([local, "replay", str(recording)])
assert replayed == expected, "Kafka recording replay differs"
(output_dir / "replayed.events").write_bytes(replayed)

# A real process exit and restart using committed broker offsets.
group = topic + "-restart"
prefix = run([kafka, "consumer", *common, "--group", group, "--max-events", "6"])
suffix_output = run([kafka, "consumer", *common, "--group", group])
assert prefix + suffix_output == expected, "restart duplicated or skipped visible events"
assert run([kafka, "consumer", *common, "--group", group]) == b"", "completed group emitted twice"
(output_dir / "restarted.events").write_bytes(prefix + suffix_output)

# Recorder reconstructs from retained prefix; same group must not produce a suffix-only file.
run([kafka, "recorder", *common, "--group", topic + "-recorder", "--output", str(recording)])
assert recording.read_bytes() == expected, "recorder reconstruction differs"
run([kafka, "producer", *common, "--run-id", "42"], success=False)
print(f"PASS: queued delivery, independent groups, incremental recording/replay, 6-event restart, completed offsets, recorder reconstruction")
print(f"Evidence: {output_dir}")
print(f"Topic retained for inspection: {topic}")
