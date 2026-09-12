# Procedural scenarios (version 1)

The platform owns a small deterministic scenario generator in
`src/ProceduralScenario.hpp/.cpp`. `ProceduralConfig` feeds `generateScenario`,
which returns core entities and platform sensor configurations. `runProcedural`
uses the existing `RunSession` and `MultiSensorRunner`, emitting the unchanged
typed lifecycle/measurement events. Recording, fusion, ingestion, analytics and
the viewer consume those events normally. No evaluation truth is exported.

## Configuration and CLI

| Field | Default | Accepted values |
| --- | --- | --- |
| Scenario seed | 2026 | Unsigned 32-bit integer, including zero |
| Sensor-layout seed | 73 | Unsigned 32-bit integer, including zero |
| Duration | 20 seconds | Integer 4..120 |
| Target count | 4 | Integer 1..12 |
| Sensor count | 3 | Integer 1..8 |

`python scripts/dev.py demo --help` exposes these as `--scenario-seed`,
`--sensor-layout-seed`, `--duration`, `--target-count`, and `--sensor-count`.
The Python adapter writes `scenario.config`; it does not generate the world.
The versioned file has a header and five whitespace-separated integers in the
table's order:

```text
SENSOR_PROCEDURAL 1
2026 73 20 4 3
```

The runtime accepts that same configuration independently of the demo workflow:

```sh
python scripts/dev.py run --procedural demo/results/scenario.config --run-id 100 --record build/generated.events --layout-output build/generated.layout
python scripts/dev.py viewer build/generated.events --layout build/generated.layout
```

`--procedural` is mutually exclusive with `--experiment` and `--sample-seconds`.
`--layout-output` requires `--procedural` and is optional for headless callers.
Malformed/out-of-range configuration is rejected before simulation events are
emitted. The original `run`/`record` sample and Kafka sample are unchanged.
The viewer's compact controls call the same C++ configuration and generator
through a headless recording adapter. See [viewer controls](viewer.md).

## Target rules and motion

The core `ProceduralSpawnSystem::generatePath` supplies seeded inward paths,
pass offsets, speeds and maneuver parameters using core `SensorScenario`,
`ScenarioPathMotion` and `Entity` types. The platform rotates the paths into
evenly spaced approach sectors with seeded rotation and small angular jitter.
Targets begin approximately 150 coordinate units from the origin and aim near
it, with a pass-offset parameter bounded by 25. There are no additional spawns,
despawns or target interactions/forces during the run.

Base speed is drawn from `[280/duration, 320/duration]`, making the spatial
encounter similar across durations. A seed-rotated cycle assigns straight,
bowed-arc, zigzag and acceleration-burst behavior; four targets exercise all
four. Arc/zigzag amplitude is 12..24 units. Zigzags complete 1..1.5 cycles per
run. Bursts increase speed by 1.3..1.5 at 45..55% of the duration and retain
that increased speed; they are abrupt speed changes, not force integration.

Core currently exposes generated path descriptions but its richer executor is
inside sandbox-app orchestration. The new platform evaluator executes the small
supported subset without linking or copying that app: forward displacement is
linear (piecewise linear for bursts), arc lateral displacement is a sine bow
over path distance, and zigzag lateral displacement is a triangle wave. An arc
here is a bowed transit, not an exact constant-turn-rate circle. Positions and
velocities are evaluated at absolute simulation time, including at initialization,
so procedural paths do not depend on integration history. The existing core
constant-velocity/bounce update remains in place for unmanaged sample/experiment
entities; generated entities receive their procedural state before scanning.

## Sensor layout and overlap

Sensors occupy evenly spaced sectors of a ring with independent seeded rotation
and jitter, at radii 55..80 units from the origin. Each radar's range is its ring
radius plus 170..190 units. All have full 360-degree coverage, so every radar
covers the common origin-centred disk of radius 170. Layout generation depends
only on layout seed and sensor count, not target seed/count or duration.

The first three sensors always include 1, 2 and 4 Hz cadences in a seed-selected
order; further sensors repeat the quality/cadence cycle. Faster sensors have
lower quality: position-noise amplitudes are respectively 0.3..0.6, 0.95..1.25,
and 1.6..1.9 units; detection probabilities are 0.98, 0.91 and 0.84; false-positive
rates are 0.05, 0.15 and 0.25 per second. Their measurement seeds derive only
from layout seed and sensor ID. Core sensing supplies its existing deterministic
Cartesian noise, detection hash rolls and at-most-one false return per scan.
These are abstract radar measurements, not a physical RF/environment model.

The geometry keeps every target jointly observable throughout the first half
of the run and brings every target within 60 units of the origin at halfway.
Thus several targets are simultaneously observable and their paths share an
encounter area, while exact collisions are neither required nor enforced.
Targets subsequently separate and some may leave individual sensor circles;
an exit from all coverage is not guaranteed. Even a one-sensor request retains
basic observability, though multi-sensor overlap requires at least two sensors.
Tests sample independent seed pairs, minimum/maximum duration and multiple counts
to check coverage, convergence, finite trajectories and motion diversity.

## Repeatability and viewer

Simulation polls at fixed 8 Hz from zero through duration inclusive. Sensor
cadences divide that tick rate exactly; each sensor scans initially and at the
endpoint. For rates `r_i`, scan count is `sum(duration * r_i + 1)`, and event
count adds one run start, one start per sensor and one run finish. Measurement
counts depend on generated coverage, misses and clutter.

Same configuration and seeds produce byte-identical recordings on the same
build/toolchain. Integer mixing is explicit; trigonometric floating-point
results are not promised bit-identical across platforms. Run ID is an event
identity, not a generation seed. Changing only target seed preserves the whole
network, while changing only layout seed preserves all target motion.

`writeScenarioLayout` serializes positions/ranges from the actual generated
sensor vector using round-trip float precision and the existing `SENSOR_LAYOUT 1`
format. It contains geometry only, with no target truth. The demo prepares the
existing viewer command; playback still uses recording events and platform
fusion. The viewer can also prepare a recording using its Generate / Run action;
event contracts, analytics and Kafka behavior remain unchanged.
