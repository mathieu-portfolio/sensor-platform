# Controlled load and failure experiments

`experiments/` runs the C++ simulator and a separate consumer process over either
an OS pipe or the existing single-partition Kafka transport. JSON config, resolved
runtime plan, recordings, process logs, timestamp samples and a JSON summary are
retained together. Domain events and sensor_core are unchanged. DuckDB is needed
only for reporting, using the existing `analytics/requirements.txt` dependency.

## Run and compare

From sensor-platform, after building the runtime and installing the analytics dependency:

```powershell
.venv/Scripts/python.exe -m experiments run experiments/configs/baseline.json build/experiments/local-baseline --bin-dir build/Debug
.venv/Scripts/python.exe -m experiments run experiments/configs/load.json build/experiments/local-load --bin-dir build/Debug
.venv/Scripts/python.exe -m experiments run experiments/configs/pause.json build/experiments/local-pause --bin-dir build/Debug
.venv/Scripts/python.exe -m experiments run experiments/configs/outage.json build/experiments/local-outage --bin-dir build/Debug
.venv/Scripts/python.exe -m experiments run experiments/configs/delayed.json build/experiments/local-delayed --bin-dir build/Debug
.venv/Scripts/python.exe -m experiments report build/experiments
```

On Unix use `.venv/bin/python` and the single-config binary directory. Output
directories must be new; evidence is never overwritten. The report executes
`experiments/sql/comparison.sql` over the `*/summary.json` files with DuckDB and
prints CSV. Failed experiments stay in the comparison with `integrity_pass=false`.

For Kafka, build with `SENSOR_PLATFORM_KAFKA=ON` and start the broker as described
in [Kafka development](kafka.md). Append `--transport kafka` to the same commands
and select the Kafka-enabled binary directory. Each experiment creates a fresh
one-partition topic and consumer group; topics are retained for inspection. Topic
creation defaults to `docker compose exec` from the repository root. For a native
broker, pass `--kafka-home <Kafka-installation> --java <Java-executable>`;
`--brokers` defaults to `localhost:9092`. No broker is started implicitly.

Local mode preserves `run` and `replay` and adds `observe`, which reads a live
recording from stdin and validates/writes each event incrementally. Kafka mode
uses the existing producer and viewer, including their committed-offset rules.
The experiment pause is a controlled processing sleep, not a crash or rebalance.
The existing `tools/validate_kafka.py` remains the actual process exit/restart,
queued-delivery and recorder reconstruction validation path.

## Configuration and scenarios

JSON accepts only the fields defined in `experiments/config.py`; unknown fields
fail. `config.json` in each result contains resolved defaults. Key fields:

- `run_id`, `duration_seconds`, `tick_hz`, `sensor_count`, `scan_hz`, `seed`.
  Cadences cycle through `scan_hz` across sensor IDs 1..N. Position is a deterministic
  10-unit grid; each ID gets a seed derived from the base seed. The plan lists
  each sensor explicitly. Coverage is 1000 world units, range noise 2, detection
  probability 0.9, with the existing default FOV and false-positive rate.
- `wall_seconds_per_sim_second`: pacing target, default 1; zero runs unpaced.
  Backpressure can make a run slower than the target. Polling timestamps remain
  exactly the configured tick sequence; wall-clock delays never alter physics.
- `consumer_delay_ms`: processing delay per event; `consumer_start_delay_ms`:
  delayed process launch while the producer continues.
- `pause_after_events` and `pause_ms`: one bounded consumer processing pause.
- `outage`: `{ "sensor_id": 2, "start": 0.5, "end": 1.5 }` in simulation seconds.

Duration must contain an integral number of ticks; polling frequency must be at
least the largest scan frequency. Arbitrary cadences are observed at the next
poll, matching existing core semantics. Range/noise/world setup is intentionally
concrete rather than a new general scenario framework. Seed plus resolved plan
reproduces the event stream; wall-clock measurements will vary.

Included configs run for two simulated seconds: baseline has three sensors at
4/8/16 Hz; load has sixteen at 40 Hz; pause stops processing for one second after
ten events; outage disables sensor 2 during [0.5,1.5); delayed starts the consumer
500 ms late and adds 40 ms per event. Outage skips sensor polling without resetting
its sequence or RNG state. The world and other sensors continue. Recovery emits
one current scan when due, never synthetic scans for the outage. There is no new
lifecycle event: the retained config explains the gap in acquisition timestamps.

## Metric definitions

Simulation timestamps describe acquisition/world time only. Transport metrics use
`system_clock` epoch nanoseconds recorded by C++ processes on the **same host**.
Clock resolution may be coarser than a nanosecond. Cross-host clocks are not supported;
backward steps or negative latencies invalidate the result, though not every clock
adjustment is detectable. Scheduling/pacing uses a monotonic clock.

| Metric | Definition |
| --- | --- |
| Produced/consumed events per second | `(N-1)/(last-first)` timestamp interval for each process, excluding startup/teardown; counts all event types, not detections |
| Latency, p50/p95/p99 | Consumer output flush completion minus timestamp immediately before producer output/publish; includes queueing, startup, intentional delay and processing, but excludes the following consumer offset commit |
| Backlog | Produced identities not yet output by the consumer, reconstructed at every timestamp; includes in-flight events and pipe/client/broker queues |
| Maximum/final backlog | Peak and final outstanding counts; this is application lag, not Kafka high-watermark minus committed offset |
| Catch-up seconds | Time from resume marker to the first zero backlog, or null if no pause/no recovery; includes newly arriving work |
| Integrity | Totals, duplicates, missing identities, conflicting duplicate payloads, unexpected identities, order violations and payload mismatches |

Percentiles use linear interpolation at `(N-1)*p`; empty samples yield null.
One-event/zero-duration throughput yields null. Consumer rates can exceed producer
rates during draining. Small bursts count toward maximum backlog even in a healthy
run. Local pipes exert backpressure when full; Kafka can retain much larger queues.
These differences matter when comparing transports.

An unpaced reference run from the same plan supplies expected events. The received
stream must match it and pass the existing complete-file C++ replay validation.
Duplicate events are reported as failures here, not normalized as historical export
does. Kafka's existing validator still rejects gaps/duplicates before output;
such failures appear in process errors/stderr and fail the experiment even when
the rejected event did not reach the output-based duplicate counter. Malformed
records, missing traces, unexpected exits and timeouts also fail. A requested pause
that never occurs or never catches up fails. Raw evidence is retained on failure.

`produced.csv` and `consumed.csv` retain raw timestamp/phase samples; `latency.csv`
and `backlog.csv` retain derived samples separately from `summary.json`. Summaries
include configuration, environment, UTC start/end, process exit codes, sensor scan/
detection counts and checks. Analysis currently loads one modest run in memory.
Instrumentation flushes timestamp samples per event and contributes overhead.

## Actual local comparison

Measured on 2026-09-11, Windows 11 build 26200, MSVC Debug binaries, native Kafka
4.0.0 / Java 21, single broker on the same development machine. Five scenarios
were run sequentially per transport. These are one-off engineering observations,
not universal capacity or latency claims. Kafka startup/coordinator delay is
included; no warm-up or tuning was applied.

| Scenario / transport | Events | Produced/s | Consumed/s | p50 ms | p95 ms | p99 ms | Max backlog | Recovery s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline / local | 64 | 31.36 | 31.36 | 0.44 | 0.95 | 1.53 | 6 | — |
| Load / local | 1314 | 653.81 | 653.67 | 0.51 | 1.30 | 1.87 | 14 | — |
| Pause / local | 64 | 31.29 | 31.31 | 1.32 | 930.39 | 963.44 | 29 | 0.004 |
| Outage / local | 56 | 27.46 | 27.45 | 0.36 | 0.85 | 4.22 | 6 | — |
| Delayed / local | 64 | 31.43 | 20.90 | 1091.62 | 1450.22 | 1533.94 | 33 | — |
| Baseline / Kafka | 64 | 31.29 | 57.68 | 499.14 | 1007.50 | 1044.86 | 32 | — |
| Load / Kafka | 1314 | 647.21 | 63.11 | 10322.60 | 18765.65 | 19503.48 | 1243 | — |
| Pause / Kafka | 64 | 24.98 | 31.28 | 839.53 | 1383.41 | 1422.64 | 42 | 0.848 |
| Outage / Kafka | 56 | 27.27 | 50.74 | 440.62 | 1026.81 | 1061.65 | 28 | — |
| Delayed / Kafka | 64 | 31.26 | 15.73 | 2527.99 | 3305.82 | 3453.69 | 55 | — |

All ten had zero missing/duplicate/conflicting/out-of-order events, matching
payloads, successful replay validation and final backlog zero. Outage reduced
sensor 2 from 17 scans to 9; sensors 1 and 3 retained 9 and 33 scans. Unit tests
also compare those unaffected sensors' full measurement streams.

The consumer drain rate is the observed load bottleneck. Its synchronous per-event
offset commit, Windows scheduling, Debug build and output/metric flushes are plausible
contributors; these runs do not isolate their individual costs. Next: controlled
Release-build comparisons and bounded commit batching with explicit restart/crash
tests, preserving at-least-once integrity before claiming a throughput improvement.

## Historical analysis and tests

Experiment recordings remain normal historical input:

```powershell
.venv/Scripts/python.exe -m analytics export build/experiments/local-outage/received.events build/experiment-data --runtime build/Debug/sensor_platform.exe
.venv/Scripts/python.exe -m analytics query build/experiment-data --sql analytics/sql/scan_cadence.sql
$env:SENSOR_PLATFORM_RUNTIME = 'build/Debug/sensor_platform.exe'
.venv/Scripts/python.exe -m unittest discover -s experiments/tests -v
.venv/Scripts/python.exe -m unittest discover -s analytics/tests -v
```

Kafka-outage export was also validated: 56 events, 51 scan rows, 46 detections.
The existing sensor summary SQL reports the reduced volume, and scan cadence SQL
shows the acquisition-time gap. Reusing the same run ID with an identical local/
Kafka recording is a no-op; changed experiment configurations require distinct run
IDs when retained in one historical dataset.
