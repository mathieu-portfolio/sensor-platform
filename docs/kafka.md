# Kafka development workflow

The domain contract stays in sensor_core. All Kafka code, serialization and file
I/O live in sensor-platform. There is one simulation producer process; a text
consumer and recorder use separate consumer groups to receive independent copies.
"Viewer" below names that text consumer role/group. The separate
[graphical viewer](viewer.md) reads completed recordings, not Kafka directly.

## Build and start

Local builds stay Kafka-free by default. Enable the additional executable with:

```sh
cmake -S . -B build-kafka -DSENSOR_PLATFORM_KAFKA=ON
cmake --build build-kafka --config Debug
ctest --test-dir build-kafka -C Debug --output-on-failure
docker compose up -d --wait
docker compose exec kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:19092 --create --topic sensor-run-42 --partitions 1 --replication-factor 1
```

CMake uses an installed RdKafka package if available, otherwise fetches pinned
librdkafka v2.10.1. The fallback builds a static plaintext client with optional
SSL/SASL/compression dependencies disabled. The local broker is pinned to Apache
Kafka 4.0.0 in single-node KRaft mode. Only localhost:9092 is published.
Docker Desktop needs working Linux-container virtualization.

Use the executable paths below for Visual Studio; single-config generators place
them directly in build-kafka. Start the producer before either downstream process:

```sh
build-kafka/Debug/sensor_platform_kafka.exe producer --topic sensor-run-42 --run-id 42
build-kafka/Debug/sensor_platform_kafka.exe consumer --topic sensor-run-42 --group viewer-42
build-kafka/Debug/sensor_platform_kafka.exe recorder --topic sensor-run-42 --group recorder-42 --output build-kafka/kafka.events
build-kafka/Debug/sensor_platform.exe replay build-kafka/kafka.events
```

Producer and consumers default to localhost:9092; override with `--brokers`.
Each exits when the run finishes. The default idle/delivery timeout is 15 seconds
(`--timeout-ms`). Broker errors and incomplete streams exit nonzero.
`docker compose down` stops the broker while preserving its data volume.

## Message and ordering contract

Each Kafka value is `SENSOR_EVENTS 1\n` followed by exactly one existing event
record and newline. The key is the decimal run ID. No event fields or domain
types changed, and there is no schema registry.

This milestone uses **one fully retained topic per run, exactly one partition,
and one active producer**. Every event is explicitly sent to partition 0.
Create a fresh topic per independent run; the producer rejects nonempty topics.
Clients reject multi-partition topics and expired prefixes. Do not compact these
topics or increase their partition count. Keep the complete run within retention.

The existing stream sequence remains the total order across sensors and resets.
Kafka preserves that order within this partition; no cross-partition order is
claimed. This trades throughput and topic count for a simple verifiable boundary.
The empty-topic check is not a concurrent-producer lock: operators must not start
two producers against the same topic.

## Delivery and restart semantics

The producer enables librdkafka idempotence and waits for acknowledged delivery
(`acks=all`) for each event. That handles library retries within a producer
session. A failed/interrupted producer may leave a partial topic; start a new
run/topic instead of blindly republishing. No producer restart transaction exists.

Consumers explicitly assign partition 0, disable automatic offset storage/commit,
and synchronously commit the next offset **after** successful validation and
output/file flush. There must be one active process per group; this implementation
does not use subscription rebalancing. Viewer and recorder must use different
groups. Kafka offsets are broker-owned, not inferred from local files.

Every invocation reads the retained prefix from offset zero to rebuild bounded
validation state. The viewer suppresses events before its previously committed
offset. It prints a format header only for a fresh group, so concatenating a
checkpointed viewer's stdout with its restarted stdout yields the complete run:

```sh
build-kafka/Debug/sensor_platform_kafka.exe consumer --topic sensor-run-42 --group restart-42 --max-events 6
build-kafka/Debug/sensor_platform_kafka.exe consumer --topic sensor-run-42 --group restart-42
```

The first command is an orderly process exit after six flushed/committed events.
A crash between output and commit can cause repeated visible events on restart:
delivery is **at least once**, not exactly once. Duplicate/missing stream
sequences within the topic fail before processing or committing that event.
An already completed viewer group revalidates the prefix and emits nothing.

The recorder recreates its specified output file from the retained topic on every
invocation, including events before its committed offset. It never creates a
suffix-only recording on restart. Each event is validated, appended and flushed
immediately; only per-sensor validation state is retained, not the whole run.
File flush is not fsync, and file writes and Kafka commits are not atomic.
A failed recording remains partial and whole-file replay rejects it. Restart
reconstructs it from Kafka; this requires the complete retained prefix.

Live local recording uses the same incremental writer and EventSink callback.
Replay still parses/validates the whole file before any output and never starts
simulation or Kafka. There is no generic event bus.

## Integration validation

With the broker running, Python 3 can drive the separate C++ processes:

```sh
python tools/validate_kafka.py --bin-dir build-kafka/Debug
```

It creates a unique one-partition topic, publishes with consumers absent, compares
viewer/file/replay output to the local run, exits/restarts a viewer after six
events using the same group, checks completed offsets emit nothing, and rebuilds
a recorder file with the same group. Evidence files remain beside the executables.
The topic is retained for inspection. Unit tests never require Kafka.

For a broker run directly with Java, the same script accepts `--kafka-home` and
`--java` for native topic administration instead of Docker. Runtime validation
results for this change are recorded in the architecture document.

References: [Apache Kafka Docker setup](https://kafka.apache.org/40/getting-started/docker/),
[librdkafka delivery and offset management](https://docs.confluent.io/platform/current/clients/librdkafka/html/md_INTRODUCTION.html).

[Controlled load/failure experiments](experiments.md) and downstream
[raw/clean analytics](analytics.md) are implemented. Broader broker-crash tests,
durable checkpoints and commit-batching comparisons remain future work.
