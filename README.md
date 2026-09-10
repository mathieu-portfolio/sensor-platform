# radar-platform

A portfolio project exploring C++ simulation, distributed systems, event-driven architecture, and Data Engineering through a multi-radar simulation and data platform.

The starting point is the domain knowledge in the sibling `sensor-sandbox` repository: a working C++20/raylib simulation with noisy detections, tracking, prediction, procedural scenarios, and visualization. The sandbox remains a separate working application. This repository currently contains project foundations and design documentation only; it has no executable, build target, or dependencies.

The intended progression is a small headless simulation boundary, independent radars observing one authoritative world, typed local events, recording/replay, and then separate processes and downstream data processing. Ground truth stays centralized. Distribution begins around sensor observations, tracking, recording, and consumers; it does not distribute world physics.

The first implementation milestone lives in sensor-sandbox: its simulation target and domain tests can build without raylib, and the single-sensor API takes read-only entities and explicit simulation time. This keeps one canonical implementation while reuse packaging remains undecided. No code has been copied or extracted, and no submodule or infrastructure has been introduced.

- [Architecture](docs/architecture.md): observed implementation, coupling, reuse options, and proposed boundaries.
- [Roadmap](docs/roadmap.md): incremental scope and measurable exit criteria, beginning with a small domain boundary milestone.

Local checkout note: this foundation was initialized in the existing `sensor-platform/` directory next to `sensor-sandbox/`. The project name is `radar-platform`; renaming the checkout is optional and does not change the design.
