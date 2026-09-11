# radar-platform

A portfolio project exploring C++ simulation, distributed systems, event-driven architecture, and Data Engineering through a multi-radar simulation and data platform.

The sibling `sensor-sandbox` repository contains a working C++20/raylib simulation and the reusable `sensor_core` library. This repository now builds a small headless executable that consumes that library. The repositories remain separate.

The intended progression is a small headless simulation boundary, independent radars observing one authoritative world, typed local events, recording/replay, and then separate processes and downstream data processing. Ground truth stays centralized. Distribution begins around sensor observations, tracking, recording, and consumers; it does not distribute world physics.

The executable advances one straight-moving entity and samples it with one 2 Hz sensor using explicit simulation time. CMake adds the sibling checkout as a subdirectory with sandbox app/tests disabled and links only `sensor_core`. No raylib, copying, vendoring, or infrastructure is involved. Extraction into a third repository remains deferred.

## Build and run

Requires CMake 3.20+, a C++20 compiler, and `../sensor-sandbox` containing the reusable core target. Run from this repository:

```sh
cmake -S . -B build
cmake --build build --config Debug
ctest --test-dir build -C Debug --output-on-failure
```

Run `build/Debug/sensor_platform.exe` with Visual Studio, or `./build/sensor_platform` with a single-configuration generator. Expected output is three scans at 0, 0.5 and 1 second, with entity X positions 100, 105 and 110. The test verifies this complete output.

Override the sibling location with `-DSENSOR_SANDBOX_SOURCE_DIR=/path/to/sensor-sandbox`. The build consumes that checkout's current sources; it does not pin a Git revision or modify its build directory.

- [Architecture](docs/architecture.md): observed implementation, coupling, reuse options, and proposed boundaries.
- [Roadmap](docs/roadmap.md): incremental scope and measurable exit criteria, beginning with a small domain boundary milestone.

Local checkout note: this foundation was initialized in the existing `sensor-platform/` directory next to `sensor-sandbox/`. The project name is `radar-platform`; renaming the checkout is optional and does not change the design.
