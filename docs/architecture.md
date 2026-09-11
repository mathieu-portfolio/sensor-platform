# Architecture

## Status and evidence

This document separates observations from proposals. sensor-platform now builds a headless C++ consumer of the sibling sensor-sandbox core. Earlier implementation sections record historical milestones; the original inspection sections describe the baseline revision, not the updated build/API.

## Reusable core and platform consumer

`sensor_core` now lives in sensor-sandbox and contains presentation-independent world/motion, sensors/measurements, evaluation, tracking, scenarios, timing and instrumentation. The former presentation library is named `sensor_sandbox_presentation`. Sandbox-specific `SensorSimulation` orchestration moved to `src/app/simulation/` and builds as `sensor_sandbox_runtime`; its frame views and echo history are outside the core. Domain tests link the core directly, while the separate runtime regression suite remains runnable without raylib.

sensor-platform uses CMake `add_subdirectory` on `../sensor-sandbox` (overridable with `SENSOR_SANDBOX_SOURCE_DIR`) and links `sensor_platform` only to `sensor_core`. Sandbox app/tests are disabled in this embedded build. No sources are copied, vendored, or merged; both checkouts remain independent Git repositories. Consumption uses the current sibling working tree, not a pinned or installed package. Extraction into a third repository remains deferred.

The executable constructs one straight-moving entity and one 2 Hz sensor, advances world motion once per 0.25-second step, and passes explicit elapsed seconds to the scanner. It prints three scans at 0, 0.5 and 1 second. A CTest fixture checks complete output, including positions and the absence of intermediate scans.

Remaining coupling: scenario definitions share tuning that includes audio volume; entities retain scenario path state; tracks retain history and truth identity. The public include root is still `src`, although core headers do not include presentation headers. Procedural transit orchestration remains in the sandbox runtime. These are follow-up concerns, not reasons to import that runtime into platform.

Next: prove independent per-sensor schedules against one authoritative world using one existing `SensorSystem` per sensor, with cadence/reset/order-independence tests. Tracking association cleanup can proceed separately before platform adds tracking.

## First boundary implementation

Implemented in sensor-sandbox commit `56ac040f32b9aa741c9f02266eb9b0ef06c9ab91` (`Establish headless sensor timing boundary`). Validation on Windows/MSVC 19.44: 49 headless tests passed with raylib discovery disabled; the interactive executable built, and all 54 app-enabled tests passed, including five audio tests. Validation used the existing pinned GoogleTest v1.15.2 source after the installed GoogleTest binaries crashed during discovery. The GUI was not manually exercised.

The small milestone refines the existing sandbox rather than creating a second platform-owned probe. `sensor_simulation` no longer links presentation code. With `SENSOR_BUILD_APP=OFF`, neither raylib discovery nor UI/audio/rendering targets are required. Domain tests link only simulation and GoogleTest; audio tests use a separate target when the app is enabled. This is an internal target boundary, not an extracted or published package.

`SensorSystem::scan` now accepts one `Sensor`, a `std::span<const Entity>`, and elapsed simulation seconds. Its optional result distinguishes not-due from a completed scan containing zero or more detections. Each completed scan carries sensor ID, a one-based sequence reset per run, and the supplied acquisition time. Callers own world evolution and sensor pose; scanning does not advance or mutate the world. Positions retain sandbox world units, time is seconds, and angles are radians.

Time must be finite, nonnegative, and nondecreasing until reset. The first call is due; later deadlines retain the existing 0.1 ms float tolerance. A late call observes the current world once and schedules the next scan from that time; there is no catch-up against fabricated historical positions. Changing the refresh rate takes effect after the next due scan. Two small corrections accompany the boundary: rates below 1 Hz respect their full interval, and not-due calls no longer increment the empty-scan metric.

The interactive application still supplies frame deltas to `SensorSimulation`, which advances its own elapsed time before invoking the sensor. No new render clock, accumulator, or physics policy is introduced. Headless callers can provide a fixed simulation schedule directly. Identical inputs and schedules are reproducible in the same numeric environment; different late-call schedules are not promised to be equivalent. Tests cover world observation, deadlines, polling, late calls, invalid time, reset with noise/drop/false returns, and pause/resume integration.

The canonical code stays in sensor-sandbox for now. Remaining coupling includes the rendering-owned frame header, mixed tuning, scenario state, and truth-assisted tracking. Measurement truth is now separated as described below; the legacy tracker still associates by entity ID through an explicit compatibility input. The smaller scan API does not constitute multi-radar support or a general reusable package. Revisit extraction only when a second consumer needs it.

## Measurement truth separation

`Detection` now contains only detection ID, sensor ID, estimated position, confidence, and uncertainty radius. Acquisition time and scan sequence remain in `SensorScan`, whose header can be consumed without world/evaluation headers. Neither type contains a truth link. Visual age moved into `DetectionEcho`, together with debug false-return coloring.

The simulator optionally fills a separate vector of `DetectionTruth` through the scanner's `evaluationTruth` output argument. Each annotation is keyed by sensor ID and detection ID and has an optional source entity ID: no entity means a known simulated false return. Omitting this output does not alter measurements or timing. A valid call replaces the vector, including clearing it when no scan is due. Annotations belong to that scan/run only; callers must not reuse them across reset because IDs restart.

`associateUsingTruth` joins processed measurements to annotations by identity, preserving measurement order even after filtering/reordering. It rejects missing or duplicate matching annotations and skips known false returns. Its `TruthAssociatedDetection` output is explicitly for the existing tracker. The tracker still stores `Track::sourceEntityId` and matches on that identity; its prediction and lifecycle algorithms are unchanged. This preserves the sandbox baseline, not realistic association. Simulation orchestration also uses annotations for debug colors and false-return timeline labels, without placing them back into normal measurements.

The next small boundary step is separating association decisions from tracker state updates so truth identity can remain solely in the compatibility adapter. No measurement-based association, multi-radar behavior, transport, or package extraction is implemented here.

Validation: 55 headless tests and 60 app-enabled tests passed on Windows/MSVC using the existing pinned GoogleTest source. The interactive executable built. Tests cover truth-free consumption, optional metadata capture, keyed joins, missing/duplicate annotations, reset, tracker continuity, and debug echo behavior. No manual GUI smoke test was performed.

## Original inspection baseline

The sibling sensor-sandbox was inspected on 2026-09-10 at commit `e1fd8f4a2ff4990b4a3a232190bce3a8a7f1ba3e` (`Updated readme and docs`), with a clean Git working tree. Inspection covered the tracked source/header files, all tests, CMake configuration and scripts, documentation, content descriptors, and asset declarations. Generated build trees and dependency internals are not project architecture. The source was not modified or rebuilt during this documentation initialization. Existing test behavior below is based on reading tests, not a fresh execution result.

Source references below are paths relative to sensor-sandbox at that revision. Recent commits include shared math/prediction/UI refactoring (`c49cbfa`), burst spawning (`5edb7b3`), turn-rate coasting correction (`f4b1c65`), and operational audio (`674e426`). This is a working evolving application, not a blank domain model.

## Observed runtime and ownership

`src/app/Application.cpp` owns the window, audio device, simulation, renderer, and UI. Each frame takes raylib's `GetFrameTime()`, updates the simulation, builds a frame view, processes audio, draws the world and UI, then applies UI actions. Sliders mutate `runtimeTuning()` through a reference; pause/reset/scenario actions take effect after that frame's simulation update. `InputManager` exists but is not called by this application loop; the visible controls are driven by `UiManager`.

`src/sensor/simulation/SensorSimulation.*` owns the world, scenario manager, scan system, detection pipeline, one tracking system, metrics, timeline, runtime controls, and detection echo history. Its update order is:

1. Return if paused; otherwise advance elapsed time and tick. A nonpositive delta is replaced with 1/60 second.
2. Move/spawn/despawn scenario entities, then age visual detection echoes.
3. Set every sensor's heading from the same elapsed-time sweep and apply shared runtime tuning.
4. Scan the world, pass detections through `DetectionPipeline`, retain echoes, and record summary events.
5. Age/predict/update tracks and compare old/new tracks for timeline entries.
6. Assemble metrics, including counts derived from visual echoes and current tracks.

There is no fixed-step accumulator in the application. `SensorSimulationConfig::fixedDeltaSeconds` is a fallback, not the normal time source. Identical seeds do not imply identical results with different frame deltas: motion, scan deadlines, prediction, and spawn opportunities depend on the update sequence.

## Existing modules and reuse potential

| Area | Actual implementation | Reuse assessment |
| --- | --- | --- |
| World/math | `world/CoordinateSystem.hpp` defines a native float `Vec2`; `Vec2Math.hpp` provides math. `WorldState` exposes mutable entity and sensor vectors. | Strong candidates. Establish read-only observation access and explicit ownership without introducing raylib types. Coordinates are local 2D; physical distance units are not formally specified. |
| Entities/motion | `Entity` stores identity, pose, velocity, signal strength, and substantial scenario path state. `EntityMotionSystem` integrates velocity and bounces at fixed bounds of +/-500. | Motion/math are reusable; scenario runtime state and bounds policy should be separated as needed by the first slice. |
| Scenarios | `SensorScenarioManager::loadDefaults()` builds seven C++ presets. Transit paths support linear, sine, arc, zigzag, and acceleration-burst motion; spawning maintains a count or emits bursts. | Reusable deterministic workload concepts, but scenario configuration includes sensor parameters and all `SensorTuning`, including audio. Navigation/display labels belong to the host application. |
| Sensors | `SensorDefinition` holds range, FOV, refresh rate, noise/probability settings. `SensorSystem::scan(const WorldState&, float)` uses range/FOV checks, deterministic Cartesian noise, dropped returns, and at most one false return per sensor per scan. | Useful educational model, not radar physics. `SensorKind`, angular noise, and entity signal strength are not used to vary scan behavior. |
| Detections | `Detection` has integer detection/sensor/source-entity IDs, estimated position, confidence, uncertainty radius, and age. `DetectionPipeline::process` returns its input unchanged. | Observation values are reusable after clarifying acquisition time, identity scope, and evaluation-only truth metadata. Echo age is a presentation concern. |
| Tracking | `TrackingSystem` manages tentative/active/maneuvering/stale/lost states, confidence decay, scalar uncertainty growth, and constant-velocity/acceleration/turn-rate predictions. Shared equations live in `TrackPrediction.hpp`. | Prediction and lifecycle logic are candidates. Association and timing assumptions need explicit treatment before independent sensor pipelines. This is heuristic tracking, not a Kalman filter or covariance model. |
| Instrumentation | `SensorMetrics` stores a snapshot. `SensorTimeline` appends `SensorEvent` values to an unbounded vector until reset. | Useful local diagnostic concepts, but neither a durable event log nor an event bus. Metric definitions and event semantics need refinement. |
| Presentation | `rendering/`, `ui/`, `audio/`, `input/`, `app/`, and assets implement the interactive application. Rendering converts native coordinates to raylib `Vector2` and inverts Y. | Keep in the sandbox/application adapters. Reuse domain prediction functions where useful; do not place drawing, widgets, sounds, or window timing in the core. |

The JSON files under `content/common/` are descriptive placeholders, not the source of runtime presets. There is no `src/content` implementation, despite a CMake source glob and `SENSOR_CONTENT_DIR` definition. `SensorScenarioBuilder` returns an empty world and has a test documenting that placeholder behavior. Procedural paths are generated using scenario/run seeds and entity IDs; simulation path construction also depends on the first sensor's position and scenario sensor range, with some aim-point logic centered on the origin. World generation should eventually take explicit scenario geometry so moving or adding a radar does not implicitly redefine ground truth.

## Coupling that matters

### Source and build dependencies

Domain files under `src/sensor/` do not directly include raylib. However, `SensorSimulation.hpp` includes `rendering/viewmodels/SensorRenderFrameView.hpp` and exposes `buildFrameView()`. That frame header itself uses standard C++ and domain types, but lives on the presentation side and mixes domain snapshots with visual lifetime, UI flags, tuning, and scenario labels. Vectors are copied; scenario name/description pointers borrow strings from the scenario manager. It is not a safe asynchronous or serialization contract.

`SensorTuning` mixes sensor, tracker, and audio parameters. `Track` carries display history and an accumulating detection-ID history. `SensorSimulation` retains visual echoes and copies the full timeline into every frame, although the UI shows only four events. These are reasonable small-app choices but should not define long-running service storage or public event contracts.

`CMakeLists.txt` requires CMake 3.20 and C++20, finds or fetches raylib 5.5, and finds or fetches GoogleTest v1.15.2. Its target names obscure the dependency direction:

```text
sensor_sandbox executable -> sensor_simulation -> sensor_core -> raylib
sensor_sandbox_tests      -> sensor_simulation + sensor_core + GTest

sensor_core       = audio + input + rendering + UI sources
sensor_simulation = sensor sources (+ currently empty content source glob)
```

Both libraries are defined regardless of the app toggle. Tests therefore still pull in raylib-dependent code. The test preset descriptions saying raylib is not required disagree with the actual build graph. Presets cover default/Ninja generators and optional vcpkg toolchains; scripts default to the vcpkg debug presets and expect invocation from the repository root. Assets use Git LFS attributes. There is no standalone, installable domain target today.

### Multiple sensors are stored, but not independent

`WorldState` can store several sensors and detections retain `sensorId`. However, one `SensorSystem` owns a shared deadline, refresh counter, detection-ID counter, and aggregate statistics. On a refresh it scans every sensor and chooses the next interval as the minimum of 1 second and all sensor intervals. A slower sensor therefore follows the shared schedule; there is no per-sensor catch-up policy. `SensorSimulation` creates one central radar, synchronizes every heading, and overwrites every sensor with the same tuning on each update.

The tracker merges detections by `sourceEntityId`, ignores `sensorId` for association, and skips all negative source IDs (known false returns). `TrackAssociationConfig::maxAssociationDistance` is an unused placeholder. Feeding two radars' simultaneous returns into this tracker could update the same track twice using per-update timing assumptions. This is truth-assisted tracking, not measurement association or sensor fusion. Preserve it only as an explicitly named baseline until a measurement-based policy is introduced; truth IDs must not silently become production association keys.

### Timeline and metric semantics are not transport contracts

`SensorEvent` contains a float time, enum, generic integer `primaryId`, and human-readable label. SensorScan also labels resets/settings changes; EntityMoved marks entry, and TrackLost can mark entity exit or a stale track. Audio distinguishes operational scans by the `scan:` label prefix. Track removal can escape the old/new comparison because it iterates only surviving tracks. Detection-created/dropped enum values do not imply corresponding runtime emissions.

An empty scan return means either no scan was due or a due scan found nothing. `recordDetectionEvents` increments `noLockScanCount` for both. Detection count measures retained echoes, track count includes all retained states, and `lostTrackCount` is not populated by the simulation. These observations matter for future analytics: define scan completion, empty results, lifecycle transitions, and metric denominators explicitly before persisting them.

## Test baseline and gaps

There are 45 `TEST` cases in 11 test source files, discovered by CTest through GoogleTest. They cover world storage/motion, basic range detection, pass-through detections, scenario configuration/initial spawning, simulation frame counts, tuning, timeline order, metric storage, prediction/maneuver behavior, angle wrapping, and fake-backend audio behavior. Shared test helpers currently include the whole simulation header even for small domain fixtures.

There are no tests establishing independent radar cadence, multi-sensor association, full-run deterministic equivalence, replay, event completeness, or a raylib-free build. Sensor coverage tests check range but do not establish FOV/probability/false-return scheduling behavior. Some tests exercise placeholders or copies of tuning rather than full reset behavior. Reuse work should add focused behavioral characterization, keeping intentional behavior changes separate from mechanical boundary changes.

## Proposed target boundaries

These are logical responsibilities, not a directory or service inventory to create now.

```text
Application / run coordinator
    -> one authoritative world + scenario evolution
    -> read-only world state at explicit simulation time
        -> independent radar A -> observations -> tracker A
        -> independent radar B -> observations -> tracker B
    -> typed local events -> recorder / diagnostics / presentation adapters
                         -> later transport and downstream consumers
```

The domain and simulation code should depend only on C++20/the standard library initially. It owns values, world evolution, sensor behavior, prediction/lifecycle rules, and explicit state transitions. It must not include or link raylib, Kafka, databases, networking, or serialization libraries. The coordinator owns execution order and time advancement; the application owns wall-clock pacing, controls, and presentation. Infrastructure adapters translate domain values into storage/transport formats.

One world owner advances each tick once. Radars read the same authoritative world at the applicable simulation time and own their scan state/configuration/counters independently. Adding a radar must not advance entity motion again or change another radar's deterministic stream. Sensor pose/sweep policy is separate from world physics. Initially all of this stays in one process.

Before implementing the small boundary, specify local Cartesian coordinates, distance/time/angle units, monotonic simulation time, scan deadlines, and ID scope. Favor an integer tick as the coordinator's ordering reference and a documented fixed step for repeatable runs; choose the exact representation in the implementation milestone. Track identity should ultimately be scoped by run and tracker/sensor. Acquisition time and processing time are different concepts. Do not promise bitwise cross-platform floating-point reproducibility; declare the tested environment and numeric comparison tolerance.

Observations should expose measured values and provenance without requiring truth entity access. Ground-truth links remain available to evaluation/debug tooling through a separate path. A temporary truth-assisted tracker adapter can preserve sandbox behavior, but must be identifiable and excluded from claims about association quality. Real measurement association and multi-sensor fusion are separate later experiments.

Future typed events should represent facts such as scan completion (including zero detections), observations, and track transitions with run identity, producer identity, sequence, and simulation time. Exact payloads, schema versions, wire encoding, and delivery guarantees are deferred until that milestone. The in-memory bus belongs to orchestration; domain functions can return values/results without depending on a transport interface. Presentation labels should be derived from facts rather than parsed as facts.

Replay must distinguish replaying recorded observations through tracking from regenerating the world/sensors from a seed. The former needs acquisition times, ordering, configuration, and tracking time progression even during gaps. The latter also needs scenario/model versions, seeds, commands and their application ticks, and a time-step policy. Neither can be recovered reliably from the existing UI timeline.

## Reuse strategy: decide the boundary before the package

An eventual reusable radar/simulation core is feasible because native math and algorithms already avoid graphics APIs. Feasibility at source level is not a finished packaging boundary. First prove a small headless world-to-sensor slice, then decide ownership using evidence from two consumers.

| Option | Benefit | Cost / condition |
| --- | --- | --- |
| Narrow standalone target hosted in sensor-sandbox | Keeps original code and behavioral tests near their current owner; sandbox can consume it directly. | Requires separately scoped changes there; consumers must not build its UI targets. Cannot simply add the current repository as a subdirectory. |
| Core hosted in radar-platform, sandbox consumes a release | Keeps platform development together while allowing a small package. | Requires an intentional migration and compatible sandbox adapter; platform infrastructure must stay outside the exported core. |
| Separate core repository consumed by both | Clear independent ownership and releases. | Adds a third repository, release/version coordination, and maintenance before the API has proven useful. Defer until justified. |
| Independently maintained copies | Fast initial exploration. | Diverging fixes and semantics undermine reuse. Avoid as the long-term strategy; any small experimental port needs recorded provenance and an explicit retirement/migration decision. |

After the boundary is proven, a versioned CMake target/package could be consumed by both applications using `find_package`, with a pinned source acquisition or explicit local development override if needed. Exact target/package names, repository location, and acquisition mechanism remain open. No submodule, shared-library extraction, sibling-path build dependency, or source copy is introduced now. Prefer a source-compatible package first; there is no demonstrated need for a stable binary ABI.

For the first implementation milestone, a minimal platform-owned boundary probe can be written from the observed behavior without copying the full simulation or creating a published shared library. Keep it small and record what it deliberately models or leaves out. Use its results to select the canonical implementation before expanding duplicated behavior. Any later modification or extraction in sensor-sandbox needs a separate task; this initialization authorizes neither.

## Decisions now and decisions deferred

Now: centralized ground truth; C++20 domain direction; explicit time/ownership; infrastructure-free core; observations distinct from truth; local behavior before distribution; evidence and tests before reuse restructuring.

Deferred: canonical core repository and packaging, full scenario migration, exact public API and ID/time representation, event schemas/serialization, concurrency and process topology, Kafka settings and guarantees, database/data model choices, cloud/deployment tooling, and fusion algorithms. Add a technology only when a roadmap milestone gives it a concrete job and an observable success criterion.
