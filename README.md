# radar-platform

A portfolio project exploring C++ simulation, distributed systems, event-driven architecture, and Data Engineering through a multi-radar simulation and data platform.

The sibling `sensor-sandbox` repository contains a working C++20/raylib simulation and the reusable `sensor_core` library. This repository now builds a small headless executable that consumes that library. The repositories remain separate.

The intended progression is a small headless simulation boundary, independent radars observing one authoritative world, typed local events, recording/replay, and then separate processes and downstream data processing. Ground truth stays centralized. Distribution begins around sensor observations, tracking, recording, and consumers; it does not distribute world physics.

The executable advances one shared world and samples it with three independently scheduled radars at 1, 2 and 4 Hz. `MultiSensorRunner` owns one `SensorSystem` per radar and passes explicit simulation time to each. CMake adds the sibling checkout with sandbox app/tests disabled; the platform runner library links `sensor_core`. No raylib, copying, vendoring, or infrastructure is involved. Extraction into a third repository remains deferred.

Configuration is a C++ `std::vector<SensorConfig>` in `src/EventTransport.cpp`: sensor ID, position, heading, existing range/FOV/cadence/noise/probability parameters, and a per-sensor seed. There is no configuration file parser. The sample uses two noise-free radars and a third with noise, dropped returns and false returns enabled.

## Build and run

Requires CMake 3.20+, a C++20 compiler, and `../sensor-sandbox` containing the reusable core target. Run from this repository:

```sh
cmake -S . -B build
cmake --build build --config Debug
ctest --test-dir build -C Debug --output-on-failure
```

Run `build/Debug/sensor_platform.exe` with Visual Studio, or `./build/sensor_platform` with a single-configuration generator. Over 0 through 1 second, inclusive, sensors 1/2/3 produce 2/3/5 scans. The typed output includes run/sensor lifecycle records and complete scan records with identities, acquisition timestamps and measurement tuples. World X advances from 100 to 110 once across the run, regardless of sensor count. Tests cover schedules, shared-world motion, independent reset, seeded repeatability, sensor reorder/removal, invalid inputs and the executable output.

The runner samples at caller-provided timestamps (0.25-second steps in the sample). A late poll observes the current world once and schedules from that time; it does not reconstruct missed scans. Resetting one sensor restarts only its local sequence/deadline, retaining its seed. The shared clock and world continue. Sequence and detection IDs are local to a sensor between resets; they are not durable identifiers across resets. RunSession now wraps these local identities in explicit run/sensor generations and a global event sequence.

Record and replay the same sample (Visual Studio paths shown):

```sh
build/Debug/sensor_platform.exe run --run-id 42 --record build/sample.events
build/Debug/sensor_platform.exe replay build/sample.events
```

No arguments still runs the live sample. Live stdout, the recorded file, and replay
stdout contain the same ordered typed records (apart from OS line endings).
Recording replaces the specified file. Replay validates the complete file before
output; it never reruns the simulation. The inspectable versioned text format,
identity rules and limits are documented in [Event recording](docs/event-recording.md).
Kafka producer, consumer and incremental recorder processes are now available as an optional build. See [Kafka development](docs/kafka.md) for build/start commands, ordering and restart semantics.

Local live recording now writes and flushes events as they arrive; it no longer
buffers the complete run. Replay still validates the complete file before output.
The optional topology is simulation producer -> one-partition Kafka run topic ->
independent viewer and recorder groups. The existing local commands stay Kafka-free.

## Historical analytics

Local or Kafka-produced recordings can now be exported to immutable per-run
Parquet datasets and queried with DuckDB. Python tooling lives in `analytics/`;
the C++ runtime and sensor_core retain no analytics dependency.

```sh
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r analytics/requirements.txt
.venv/Scripts/python.exe -m analytics export build/sample.events data --runtime build/Debug/sensor_platform.exe
.venv/Scripts/python.exe -m analytics query data --sql analytics/sql/sensor_summary.sql
```

The dataset keeps separate event, scan and measurement tables, so empty scans
remain visible. Identical retries are no-ops; conflicting event/run identities
fail. The sample produces 10 scan rows and 11 measurement rows across three sensors.
See [Historical analytics](docs/analytics.md) for schema, layout, duplicate rules,
test commands and measured SQL results.

Override the sibling location with `-DSENSOR_SANDBOX_SOURCE_DIR=/path/to/sensor-sandbox`. The build consumes that checkout's current sources; it does not pin a Git revision or modify its build directory.

- [Architecture](docs/architecture.md): observed implementation, coupling, reuse options, and proposed boundaries.
- [Roadmap](docs/roadmap.md): incremental scope and measurable exit criteria, beginning with a small domain boundary milestone.

Local checkout note: this foundation was initialized in the existing `sensor-platform/` directory next to `sensor-sandbox/`. The project name is `radar-platform`; renaming the checkout is optional and does not change the design.
