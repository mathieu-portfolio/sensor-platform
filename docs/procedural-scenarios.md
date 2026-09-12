# Procedural scenarios

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

The viewer also exposes these high-level parameters. Defaults preserve the
curated scenario. Decimal input is supported; focused fields show their bounds.

| Parameter | Range | Default | Effect |
| --- | --- | --- | --- |
| Min / max speed | 1..30 each, min <= max | 14 / 16 | Base forward speed in m/s at a 20-second duration; actual speed is multiplied by `20/duration`. Bursts and lateral motion can exceed this base range. |
| Maneuver | 0..3 | 1 | Scales arc/zigzag amplitude, zigzag frequency and burst strength; zero gives constant-velocity paths. |
| Convergence | 0..1 | 1 | 1 aims paths through the common center; 0 rotates them toward tangential, dispersed transits, with seeded left/right direction. Intermediate values blend approach angles. |
| Spawn spread | 0.4..1.5 | 1 | Scales the initial radius of 150 units. |
| Coverage | 0.65..1.6 | 1 | Scales radar range, subject to the observation floor below. |
| Layout spread | 0.25..3 | 1 | Scales sensor-ring radii (55..80 units before scaling). |
| Noise | 0..5 | 1 | Multiplies each sensor's Cartesian position-noise amplitude. Zero removes position noise. |
| Reliability | 0.35..1 | 1 | Multiplies baseline detection probabilities (0.84..0.98). |
| Clutter | 0..12 | 1 | Multiplies baseline false-return rates (0.05..0.25/s). Zero disables clutter; the existing scanner caps false returns at one per scan. |

The runtime accepts `SENSOR_PROCEDURAL 2`: the original five integers followed
by ten decimal values in the table's order (min speed, max speed, maneuver,
convergence, spawn spread, coverage, layout spread, noise, reliability, clutter):

```text
SENSOR_PROCEDURAL 2
2026 73 20 4 3
14 16 1 1 1 1 1 1 1 1
```

Version 1 and the existing Python demo CLI keep their five-value format and use
the curated parameter defaults. Both file versions and viewer controls feed the
same C++ parser and generator; there is no alternate generation path.

For contrasting examples, keep the seeds fixed and try:

| Configuration | Speed min/max | Maneuver | Convergence | Spawn | Coverage | Layout | Noise | Reliability | Clutter |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Calm, dispersed, wide, clean | 8 / 12 | 0 | 0 | 1.5 | 1 | 3 | 0 | 1 | 0 |
| Maneuvering, converging, compact, noisy | 14 / 16 | 3 | 1 | 1 | 1 | 0.25 | 5 | 0.7 | 8 |

## Target rules and motion

The core `ProceduralSpawnSystem::generatePath` supplies seeded inward paths,
pass offsets, speeds and maneuver parameters using core `SensorScenario`,
`ScenarioPathMotion` and `Entity` types. The platform rotates the paths into
evenly spaced approach sectors with seeded rotation and small angular jitter.
By default, targets begin approximately 150 coordinate units from the origin and aim near
it, with a pass-offset parameter bounded by 25. There are no additional spawns,
despawns or target interactions/forces during the run.

Default base speed is drawn from `[280/duration, 320/duration]`, making the spatial
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

By default, sensors occupy evenly spaced sectors of a ring with independent seeded rotation
and jitter, at radii 55..80 units from the origin. Each radar's range is its ring
radius plus 170..190 units. All have full 360-degree coverage, so every radar
covers the common origin-centred disk of radius 170. Layout generation depends
on layout seed, sensor count and the high-level geometry parameters. The coverage
floor also uses target speed, maneuver, convergence and spawn-spread bounds,
but never target seed/count or duration. Changing only a scenario seed therefore
preserves the entire network.

The first three sensors always include 1, 2 and 4 Hz cadences in a seed-selected
order; further sensors repeat the quality/cadence cycle. Faster sensors have
lower quality: position-noise amplitudes are respectively 0.3..0.6, 0.95..1.25,
and 1.6..1.9 units; detection probabilities are 0.98, 0.91 and 0.84; false-positive
rates are 0.05, 0.15 and 0.25 per second. Their measurement seeds derive only
from layout seed and sensor ID. Core sensing supplies its existing deterministic
Cartesian noise, detection hash rolls and at-most-one false return per scan.
These are abstract radar measurements, not a physical RF/environment model.

The range floor bounds forward and lateral displacement during the first half
of the run, including the earliest/strongest possible burst. Every radar covers
that disk, regardless of seed pair, sensor count or low requested coverage.
Coverage controls can therefore saturate at this floor for demanding target
configurations. Bounds on speeds, amplitudes and spread prevent unbounded or
stationary paths; stratified approach/layout angles avoid accidental clustering.
Detection remains probabilistic: geometric coverage does not guarantee a return.

The curated defaults bring every target within 60 units of the origin at halfway.
Thus several targets are simultaneously observable and their paths share an
encounter area, while exact collisions are neither required nor enforced.
Targets subsequently separate and some may leave individual sensor circles;
an exit from all coverage is not guaranteed. Even a one-sensor request retains
basic observability, though multi-sensor overlap requires at least two sensors.
Tests sample independent seed pairs, parameter extremes and mixed configurations,
minimum/maximum duration and multiple counts to check coverage, convergence,
finite trajectories, per-parameter effects and motion diversity.

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
