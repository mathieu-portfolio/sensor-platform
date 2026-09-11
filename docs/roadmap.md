# Roadmap

Each stage produces a runnable or reviewable result with explicit exit criteria. Later stages are direction, not commitments to particular products or a service inventory. Keep the world authoritative and centralized throughout. The first implementation task separately authorized focused sensor-sandbox changes.

## 0. Foundation (this initialization)

Scope: inspect sensor-sandbox, document actual behavior and coupling, evaluate reuse, and create only documentation and repository hygiene.

Exit: README, architecture assessment, and this roadmap agree on implemented versus proposed behavior; local links and ignore rules validate; no source copied, dependencies introduced, or sandbox files changed.

## 1. Prove a small headless world-to-sensor boundary

Implementation update: the first small slice was implemented directly in sensor-sandbox instead of creating the originally proposed platform-owned probe below. It provides a raylib-free simulation/test build and an explicit single-sensor scan API with timestamped results and deterministic timing tests. Existing world motion, scenarios, and tracking remain canonical there. No shared package was extracted. The original broader criteria below remain a guide, not a claim that truth metadata, presentation headers, or the whole domain model have already been separated. The measurement truth split is now implemented: normal detections/scans have no truth IDs, optional evaluation annotations are separate, and a named truth-association adapter preserves the tracker baseline. The tracker still stores and matches entity IDs. The reusable-library milestone is now complete: sensor-sandbox owns sensor_core, and sensor-platform consumes it through sibling add_subdirectory without presentation dependencies. Extraction into a third repository is deferred. Independent per-sensor scheduling is now implemented in milestone 2; tracker association cleanup remains separate work before platform tracking.

Scope: a minimal C++20/CMake boundary probe inside radar-platform with one scripted straight-moving entity, one configured radar, and explicit simulation steps. Represent world state with native values; update the world once, then pass read-only state to a sensor operation. Return an explicit scan result that distinguishes not-due from completed-with-zero-detections. Keep sensor runtime state separate from world state. This probe now uses the canonical sibling sensor_core target; it is not a full sandbox port.

Define units, time-step/deadline behavior, identity scope, and reset semantics before writing the API. Use the sandbox's range/FOV and refresh behavior as evidence, documenting intended corrections rather than silently changing semantics. Keep truth links in evaluation data rather than requiring them in the observation interface. Do not add tracking, procedural scenario migration, UI, events, recording, or networking to this slice.

Exit criteria:

- A clean configure/build/test path compiles the slice without raylib or infrastructure dependencies, using the sibling sensor-sandbox checkout.
- A short deterministic fixture verifies entity position after known steps, inside/outside range and FOV, refresh boundaries, and an empty completed scan versus no scan.
- Repeating the same initial state/configuration/steps yields the same scan identities/times and observations within a stated numeric tolerance.
- Tests show sensor observation does not mutate world state; no rendering or audio type appears in public domain headers.
- A short design decision records the proven API boundary and the preferred canonical core owner/consumption plan. It identifies adapter work and behavior tests needed before extraction. No repository relocation is needed to finish this milestone.

## 2. Independent radars in one process (implemented)

Implemented: MultiSensorRunner in sensor-platform owns one authoritative world and one seeded SensorSystem per configured radar. The sample uses three fixed poses and rates of 1/2/4 Hz. World motion advances once per supplied timestamp; each scanner independently decides whether it is due. Noise/drop/false-return state and reset are local. Late polls sample once without catch-up. Tests verify per-stream reorder/removal independence, reset isolation, seeded repeatability and shared-world motion. Canonical core ownership remains sensor-sandbox; repository extraction is deferred.

Exit criteria:

- The three-radar sample advances entity motion once per tick and demonstrates different scan schedules.
- Including, reordering or omitting radar C does not change A/B output or world trajectory for the same run inputs.
- Sensor ID, local sequence and acquisition time identify scans within a reset epoch. Repeating the same seed/world/time sequence reproduces output; durable reset identity remains milestone 3 work.
- Independent sensor counters are validated, including completed scans with no returns.
- Both consumers build against the same sibling core checkout. Headless and app-enabled regression tests and the interactive build pass; manual GUI validation is separate.

## 3. Typed local events and explicit tracking inputs (next)

Scope: introduce small typed contracts for scan completion/observations and run/configuration/reset transitions outside the core, then connect them directly to deterministic recording/replay in milestone 4. Define stable run and reset-epoch identity before recording local scan/detection IDs. A synchronous direct consumer suffices initially; add a bus only for a concrete need. Explicit tracking inputs and per-radar tracking can follow separately, reusing prediction rules after characterization. Any truth-assisted baseline remains an explicit adapter, not an association/fusion result.

Exit criteria:

- Tracker and diagnostics consume the same facts without parsing labels or reading mutable world state.
- Run/producer identity, sequence, simulation time, payload ownership, delivery order, and subscriber failure behavior are documented and tested.
- Zero-return scans, no-scan intervals, resets, configuration changes, and deleted tracks have unambiguous semantics.
- Tests prevent simultaneous observations from different radars being accidentally treated as sequential updates to a shared track.
- The core builds without the bus or any transport; no serialization dependency is required yet.

## 4. Recording and deterministic replay

Scope: choose a minimal versioned local recording format for typed facts and run metadata. Replay recorded observations and time progression through tracking; separately support seed-driven regeneration only if its full inputs are captured. Do not treat the sandbox timeline as a recording format.

Exit criteria:

- A saved run reproduces ordered tracker transitions and final state with documented numeric tolerance, including long detection gaps and a configuration change.
- Run/model/configuration versions, seeds, time policy, event order, and reset boundaries are captured.
- Truncated/corrupt records and unsupported versions fail clearly; tests cover each.
- Playback pacing does not change simulation results. The format and replay guarantee are documented before any broker is introduced.

## 5. Transport adapter and separate processes

Scope: introduce Kafka only now, for a concrete sensor-event producer and tracker or recorder consumer. Keep a local path for comparison. The world remains owned by one coordinator; initially sensors may stay colocated with it while downstream consumers run separately. Remote sensor execution is optional later and would consume authoritative snapshots, never own physics.

Exit criteria:

- The same recorded fixture produces equivalent logical results through local and broker-backed paths.
- Document partition keys, per-producer ordering, identity, retry/duplicate behavior, offset handling, backpressure, and restart recovery. Do not claim exactly-once behavior without evidence.
- An integration test interrupts and restarts a consumer and demonstrates the chosen recovery semantics.
- Broker/client and process lifecycle code do not enter domain targets.

## 6. Historical storage and analytics

Scope: persist versioned events and build one useful derived dataset, such as scan yield and track continuity by run/sensor/time window. Choose one storage approach from actual query and replay needs; add further tools only when needed.

Exit criteria:

- Re-ingesting a recording does not duplicate logical events.
- Raw records retain provenance and support rebuilding derived tables.
- A documented query reconciles totals with the fixture and distinguishes simulated drops, false returns, and transport failures.
- A small reproducible analysis compares two runs or sensor configurations, with data-quality checks and explicit metric definitions.

## 7. Real-time processing and operational metrics

Scope: implement one streaming aggregate also computable from historical data; expose processing latency, throughput, backlog/lag, and errors separately from simulation metrics. Select an execution engine only if the workload warrants it.

Exit criteria:

- Streaming and batch results reconcile on the same fixture under documented window/late-data rules.
- Duplicate and delayed events have tested outcomes.
- A controlled slow consumer produces observable backlog and recovery; simulation time is not confused with wall-clock processing latency.

## 8. Measurement association and multi-sensor fusion experiments

Scope: first replace truth-assisted association with a small measurement-based baseline, then compare independent tracks with a simple multi-sensor association/fusion experiment. Keep this separable from infrastructure work.

Exit criteria:

- Association cannot read truth IDs; evaluation can access ground truth separately.
- Crossing, intermittent-contact, and false-return scenarios report identity switches, continuity, false tracks, and position error against a baseline.
- Coordinate frames, acquisition-time alignment, uncertainty interpretation, and duplicate observation handling are explicit.
- Results include cases where fusion worsens performance; no claim of calibrated covariance or realistic radar fidelity is made without a supporting model.

## 9. Controlled failure/load experiments and benchmarking

Scope: add repeatable experiments for sensor outages, delay, duplicates, consumer failure, and increasing entity/radar/event counts. Benchmark bottlenecks before optimizing or adding infrastructure.

Exit criteria:

- Each experiment records seed, fixture, software versions, hardware, configuration, workload, and fault schedule.
- Report throughput, latency percentiles, resource use, loss/duplication, and recovery against a stated correctness baseline.
- At least one measured bottleneck has a before/after comparison with unchanged correctness criteria.
- Publish reproducible commands and findings, including limitations and tradeoffs.

No future component needs a placeholder directory now. Continue with typed event contracts and deterministic recording/replay in milestones 3-4; retain the shared core in sensor-sandbox.
