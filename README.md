# radar-platform

A portfolio project exploring C++ simulation, distributed systems, event-driven architecture, and Data Engineering through a multi-radar simulation and data platform.

The sibling `sensor-sandbox` repository contains a working C++20/raylib simulation and the reusable `sensor_core` library. This repository now builds a small headless executable that consumes that library. The repositories remain separate.

The intended progression is a small headless simulation boundary, independent radars observing one authoritative world, typed local events, recording/replay, and then separate processes and downstream data processing. Ground truth stays centralized. Distribution begins around sensor observations, tracking, recording, and consumers; it does not distribute world physics.

The executable advances one shared world and samples it with three independently scheduled radars at 1, 2 and 4 Hz. `MultiSensorRunner` owns one `SensorSystem` per radar and passes explicit simulation time to each. CMake adds the sibling checkout with sandbox app/tests disabled; the platform runner library links `sensor_core`. No raylib, copying, vendoring, or infrastructure is involved. Extraction into a third repository remains deferred.

Configuration is a C++ `std::vector<SensorConfig>` in `src/main.cpp`: sensor ID, position, heading, existing range/FOV/cadence/noise/probability parameters, and a per-sensor seed. There is no configuration file parser. The sample uses two noise-free radars and a third with noise, dropped returns and false returns enabled.

## Build and run

Requires CMake 3.20+, a C++20 compiler, and `../sensor-sandbox` containing the reusable core target. Run from this repository:

```sh
cmake -S . -B build
cmake --build build --config Debug
ctest --test-dir build -C Debug --output-on-failure
```

Run `build/Debug/sensor_platform.exe` with Visual Studio, or `./build/sensor_platform` with a single-configuration generator. Over 0 through 1 second, inclusive, sensors 1/2/3 produce 2/3/5 scans. Every scan prints sensor ID, local sequence, acquisition time and measurement count; each measurement also carries sensor ID. World X advances from 100 to 110 once across the run, regardless of sensor count. Tests cover schedules, shared-world motion, independent reset, seeded repeatability, sensor reorder/removal, invalid inputs and the executable output.

The runner samples at caller-provided timestamps (0.25-second steps in the sample). A late poll observes the current world once and schedules from that time; it does not reconstruct missed scans. Resetting one sensor restarts only its local sequence/deadline, retaining its seed. The shared clock and world continue. Sequence and detection IDs are local to a sensor between resets; they are not durable identifiers across resets. The next milestone is typed event contracts with explicit run/reset identity, followed by deterministic recording/replay.

Override the sibling location with `-DSENSOR_SANDBOX_SOURCE_DIR=/path/to/sensor-sandbox`. The build consumes that checkout's current sources; it does not pin a Git revision or modify its build directory.

- [Architecture](docs/architecture.md): observed implementation, coupling, reuse options, and proposed boundaries.
- [Roadmap](docs/roadmap.md): incremental scope and measurable exit criteria, beginning with a small domain boundary milestone.

Local checkout note: this foundation was initialized in the existing `sensor-platform/` directory next to `sensor-sandbox/`. The project name is `radar-platform`; renaming the checkout is optional and does not change the design.
