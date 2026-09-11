# Event contract and recording format

The core value types live in sensor-sandbox at
`src/sensor/events/StreamEvent.hpp`. They contain no evaluation truth,
presentation, file I/O or transport. sensor-platform's `RunSession` converts
completed core scans and explicit lifecycle calls into these events.

## Identity and order

Every event has a nonzero caller-assigned 64-bit run ID, a run generation,
a one-based stream sequence, and a simulation timestamp in seconds.
The sequence increases across all resets. Run generation starts at zero;
`resetRun()` increments it, restores the initial scenario/configuration,
and restarts simulation time at zero. Sensor generation starts at zero in
each run generation; `resetSensor(id)` increments only that sensor's generation,
retains its seed, and leaves the world clock and other sensors untouched.

`RunStarted`, `RunReset`, `SensorStarted`, `SensorReset`,
`RadarMeasurements`, and `RunFinished` are concrete variant alternatives.
Sensor-start events declare ID, generation and seed. Each measurement event
represents a completed scan, even when empty. Not-due polls emit no event.
Measurement identity is (run ID, run generation, sensor ID, sensor generation,
scan sequence, detection ID). Scan sequences and detection IDs restart locally.

RunSession emits initialization and simultaneous scans in ascending sensor-ID
order. Lifecycle calls appear where the caller invokes them. Stream sequence
is the authoritative total order; timestamps alone are insufficient across resets.
Configuration reorder preserves the entire stream. Adding/removing a sensor
preserves other measurement contents/cadences but changes global sequence numbers.
The sample defaults to run ID 1 for repeatability; use `--run-id` to assign a
distinct identity when saving independent runs. IDs are not globally allocated.

## Text format version 1

ASCII, whitespace-separated fields, one event per line, no comments or blank
records. The header is exactly `SENSOR_EVENTS 1`. Every event begins with:

`TYPE run_id run_generation stream_sequence time_seconds`

Following fields depend on TYPE:

| TYPE | Remaining fields |
| --- | --- |
| RUN_STARTED | none |
| RUN_RESET | none |
| SENSOR_STARTED | sensor_id sensor_generation seed |
| SENSOR_RESET | sensor_id sensor_generation |
| MEASUREMENTS | sensor_id sensor_generation scan_sequence count, then count measurement tuples |
| RUN_FINISHED | none |

Each measurement tuple is `detection_id x y confidence uncertainty_radius`.
Sensor ID is inherited from its scan, reconstructing the complete normal
`Detection`. Positions use existing sandbox world coordinates. All floats
use the classic locale and `max_digits10`, preserving original finite float
values rather than rounded display values. Format versioning belongs to the
file header; unsupported versions are rejected.

Example of an empty completed scan in a complete one-sensor run:

```text
SENSOR_EVENTS 1
RUN_STARTED 42 0 1 0
SENSOR_STARTED 42 0 2 0 7 0 123
MEASUREMENTS 42 0 3 0 7 0 1 0
RUN_FINISHED 42 0 4 0
```

## Record and replay

Live: world/scanners -> RunSession -> typed events -> shared formatter + file.
Replay: file -> full parse/lifecycle validation -> typed events -> same formatter.
Replay never constructs a world, advances a clock, or invokes a scanner.

Live recording now validates, appends and flushes each event incrementally.
Replay validates the whole recording before delivering any
events. Unknown types/versions, invalid or extra fields, nonfinite values,
sequence gaps, undeclared sensor identities, invalid resets and missing final
RUN_FINISHED fail with an error and nonzero CLI exit. A partial file from an
interrupted write is rejected. This is not a crash-recovery journal or checksum
format; syntactically valid data edits are not authenticated.

Recordings preserve observations and lifecycle/seed metadata, not the complete
world/configuration needed to regenerate a simulation. Replay is independent of
the stochastic model. Tests compare every typed field, canonical text and
downstream per-sensor scan/measurement totals, including empty scans and resets.
There are no track events or replay pacing options in this milestone.

Kafka now transports these same versioned event records. See [Kafka development](kafka.md)
for topic/offset strategy and actual delivery guarantees. EventValidator retains only
per-sensor counters and lifecycle state while checking the incremental stream.
