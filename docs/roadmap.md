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
- Sensor ID, local sequence and acquisition time identify scans within a reset epoch. Repeating the same seed/world/time sequence reproduces output; explicit reset identity is now implemented in milestone 3.
- Independent sensor counters are validated, including completed scans with no returns.
- Both consumers build against the same sibling core checkout. Headless and app-enabled regression tests and the interactive build pass; manual GUI validation is separate.

## 3. Typed local events (implemented)

Core contracts now cover run start/reset/finish, sensor start/reset and completed
measurement scans. Platform RunSession assigns explicit run/sensor generations,
preserves acquisition time and orders simultaneous scans by sensor ID. Global
stream sequence continues across resets. Empty completed scans remain visible;
evaluation truth and legacy tracker events are excluded.

Validation covers lifecycle identity, reset isolation, configuration reorder,
contiguous ordering and truth-free contracts. Per-radar tracking and association
cleanup remain separate follow-up work; no bus is needed for the current consumer.

## 4. Recording and deterministic replay (implemented)

Platform owns a versioned line-oriented text format and read/write validation.
The CLI records the actual typed stream and replays saved events without running
simulation. Full-precision measurement fields and original timestamps round-trip.
The same formatter serves both paths; per-sensor downstream totals also match.

Validation covers multi-radar recording, empty scans, independent sensor and
whole-run resets, exact typed/text equivalence, malformed records, unsupported
versions and truncated files failing before any replay output. Recording is now incremental; replay buffers the complete run for validation. Full world/configuration regeneration, tracking replay and
incremental crash recovery are outside this milestone.

## 5. Transport adapter and separate processes (implemented)

Implemented: optional Kafka producer/viewer/recorder processes reuse the existing
typed records. One retained topic per run and one partition preserve total order;
viewer and recorder groups consume independently. Local execution remains
Kafka-free. Incremental recording flushes each event; replay validates the full file.

Validation: the integration script publishes before consumers start, compares
local/viewer/recorded/replayed streams, checks an orderly viewer restart after six
committed events and recorder reconstruction. Unit tests cover codec round-trips,
transport-independent handling, incremental writes and sequence rejection.

Delivery is at least once; a crash between output and offset commit can duplicate
output. No rebalance/parallel group execution, producer resumption or atomic file
checkpoint is claimed. Follow-up: controlled crash/timeout/retention tests and
durable consumer checkpoint handling alongside the historical analytics layer.

## 6. Historical storage and analytics (first slice implemented)

Python/DuckDB tooling ingests completed local or Kafka recordings into immutable
per-run Parquet event, scan and measurement tables. Empty scans and lifecycle
metadata remain queryable; evaluation truth stays excluded. Normalized event
identities remove identical duplicates and reject conflicts. Identical whole-run
re-imports are no-ops; partial runs never publish.

Six SQL analyses cover sensor yield/empty-scan rate, reset-aware cadence, run
summary, acquisition-time buckets, event types and measurement distribution.
The three-radar example reconciles to 15 events, 10 scans and 11 measurements.
Tests also cover alternate fixtures, resets and multiple run IDs.

Next: broader multi-run data-quality and retention validation, then bounded
continuous Parquet batches if workload requires them. Broker crash/checkpoint
hardening remains separate follow-up work. No new database server or orchestrator
is needed for this local historical pipeline.

## 7. Real-time processing and operational metrics

Scope: implement one streaming aggregate also computable from historical data; expose processing latency, throughput, backlog/lag, and errors separately from simulation metrics. Select an execution engine only if the workload warrants it.

Exit criteria:

- Streaming and batch results reconcile on the same fixture under documented window/late-data rules.
- Duplicate and delayed events have tested outcomes.
- A controlled slow consumer produces observable backlog and recovery; simulation time is not confused with wall-clock processing latency.

## 8. Measurement association and multi-sensor fusion experiments (baseline implemented)

Implemented in platform: world-space observations, deterministic distance-gated
nearest-neighbour matching, simple velocity prediction and global track lifecycle.
The core's older tracker is not reused; runtime fusion has no truth association.
Recorded and live text inputs share one processor and explicit global-track output.

Separate analytic fixtures evaluate overlap, asynchronous cadences, outages/noise,
false returns and crossing. The crossing exposes two identity switches despite
small position error; the persistent false return creates a false track. See
[Fusion](fusion.md) for metrics and limitations. Next compare settings/seeds and
sampling gaps before advancing the association model; covariance calibration,
late-event buffering and durable fusion checkpoints remain deferred.

## 9. Controlled failure/load experiments and benchmarking (first slice implemented)

Implemented: JSON-configured local/Kafka baseline, increased sensor count/cadence,
consumer processing pause, delayed consumer and bounded sensor outage. Timestamp
sidecars provide throughput, latency percentiles, backlog and catch-up; reference
stream/replay checks report integrity failures. DuckDB compares machine-readable
summaries. See [Experiments and performance](experiments.md) for actual results.

Remaining work:

- Isolate synchronous consumer commit/output costs in Release builds and profile resource use.
- Compare bounded commit batching with the current implementation under restart/crash tests.
- Extend controlled process-failure experiments beyond the existing Kafka restart smoke test.
- Keep before/after comparisons tied to unchanged integrity criteria and explicit local environments.

No future component needs a placeholder directory now. Continue with measured consumer batching/checkpoint hardening; retain the shared core in sensor-sandbox.
