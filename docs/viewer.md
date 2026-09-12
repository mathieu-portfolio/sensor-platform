# Event-driven recording viewer

`sensor_platform_viewer` is an optional raylib executable. It reads complete
format-v1 `.events` recordings through `readRecording` and feeds recorded events
to the existing `FusionSystem` with its default configuration. Files are validated
before the window opens. Its compact procedural controls can also prepare a new
recording using the existing platform runner, then load it through the same decoder
and playback path. Rendering and playback ticks never advance simulation.
Graphical dependencies link only to the viewer; viewer state, the procedural-run
adapter and their tests remain headless. Event contracts and fusion are unchanged.

## Build and open

Install raylib 5.5 or newer separately and make its CMake package discoverable (`raylib_DIR`
or an existing toolchain). There is no implicit download. The viewer defaults OFF.
From sensor-platform, reuse an appropriate existing build directory:

```sh
python scripts/dev.py --build-dir build/consumer-verified build --target sensor_platform_viewer -- -DSENSOR_PLATFORM_VIEWER=ON -Draylib_DIR=<installed-raylib-cmake-directory>
python scripts/dev.py --build-dir build/consumer-verified viewer build/sample.events
```

The CLI selects the binary path for your generator; use `--config Release` before
`viewer` for a Release build (default: Debug). On Windows
with shared raylib, its runtime DLLs must be beside the executable or on `PATH`.
An existing default sample recording can additionally show sensor geometry:

```sh
python scripts/dev.py --build-dir build/consumer-verified viewer build/sample.events --layout docs/sample.sensors.layout
```

To visualize the curated `demo/results` output:

```sh
python scripts/dev.py --build-dir build/consumer-verified viewer demo/results/recording.events --layout demo/results/sensors.layout
```

Arguments are forwarded to the existing viewer; `viewer --help` shows its options.
Relative paths resolve from the repository root, as with other developer commands.

To open the procedural controls without loading a file:

```sh
python scripts/dev.py viewer
```

The sidebar's **Run** tab exposes scenario seed **2026**, layout seed **73**,
duration **20 s**, **4** targets and **3** sensors by default. **Targets** adds
min/max speed, maneuver intensity, convergence and spawn spread. **Sensors** adds
coverage, layout spread, noise, reliability and clutter. See the
[parameter ranges, effects and contrasting examples](procedural-scenarios.md).
Tabs retain all values; Generate / Run uses the complete configuration across tabs.
Click a value to replace it, type digits (or decimals for the new parameters),
and use Tab/Shift+Tab to move between fields. Backspace edits; Ctrl+A selects the
whole value. Focused parameter fields show their allowed range. Enter or Escape leaves the field. Playback keyboard shortcuts are
inactive while editing. F11 toggles fullscreen even while editing; Escape leaves
fullscreen first, otherwise it closes the window when no field is focused.

Click **Generate / Run** to validate the inputs and prepare a complete recording.
Success replaces all playback state and histories, starts at time zero at 1x,
and fits the generated sensor layout with zoom and pan reset. Preparation time is
excluded from playback time. Configuration values remain unchanged in the controls.
Invalid values show a message without replacing the current recording. The same
controls remain available when a file was opened. Editing values alone does not
change playback, and the fields describe the next generated run, not metadata
inferred from a loaded file.

The headless `viewer/ProceduralRun` adapter calls `generateScenario` and
`runProcedural` with run ID 43, writes an in-memory recording through
`IncrementalRecording`, then decodes it with `readRecording`. Generated geometry
passes through `writeScenarioLayout` and `readLayout`. Defaults and validation
reuse `ProceduralConfig` and `readProceduralConfig`; there is no second generator
or UI-owned motion model. Runs are deterministic on the same build/toolchain.
Nothing is written to disk by Generate / Run; use the [demo CLI](demo.md) to retain
recordings and analytics. [Generator parameters and constraints](procedural-scenarios.md).

The layout is only an explicit annotation for that sample; never apply it to an
unrelated recording. The viewer does not infer sensor configuration or truth from
measurement positions. Without a layout the geometry count stays at zero.

## Display and controls

- Sensor-colored crosses show the latest completed scan per sensor, including its
  last position until replaced. Empty scans and sensor resets clear those crosses.
- Squares show active fused global tracks; green means confirmed, yellow tentative,
  and amber coasting. Lines show up to 32 distinct event-driven positions per track.
  Retirement removes the history. Tracks and histories clear on run reset.
- Optional sensor markers, heading rays and FOV/range outlines use world Cartesian
  coordinates with +Y up. Ground truth is never loaded or drawn.
- Counters show run/generation, acquisition time, processed events, cumulative scans
  and measurements, initialized sensors, active tracks and per-sensor counts.
  Per-sensor counters restart on sensor/run reset; totals span the recording.
  Large sensor lists show only the rows that fit; the total includes all sensors.
- Space pauses/resumes; Left/Right steps backward/forward one event and pauses; R restarts playback.
  +/- changes speed (default 1x), mouse wheel zooms, left drag pans and F fits.
  F11 toggles fullscreen, restoring windowed size, position and maximized state.
  Escape leaves fullscreen or closes the window when no field is focused.
  Completion holds the final frame; there is no simulation update
  or additional fusion prediction between recorded events.

Playback preserves source order and relative acquisition times. Equal-time events
are delivered together during timed playback. Run resets concatenate generation
timelines without inventing an unknown inter-generation delay. Left/Right stepping
allows inspection of individual same-time events and resets. The stable initial
view fits observations and layout extents; pan/zoom can inspect tracks outside it.

## Optional layout format

`SENSOR_LAYOUT 1` header, then whitespace-separated rows:

```text
run_generation sensor_id x y heading_degrees fov_degrees range
```

The column-label row above is explanatory; prefix comments with `#` in actual files.
Headings are counterclockwise from +X; FOV is (0,360], range positive. Coordinates
and range must be finite and bounded to 1e12 world units for display. Each generation
and sensor ID pair must be unique. Layout rows are drawn only after the corresponding
sensor starts in that run generation. Layout is supplied separately and is not
authenticated against the recording. No sensor pose/FOV metadata exists in v1 events;
these annotations are static per run generation and cannot represent moving sensors.

## Focused validation

```sh
python scripts/dev.py --build-dir build/consumer-verified build --target sensor_platform_viewer_tests
python scripts/dev.py --build-dir build/consumer-verified test unit -R platform_viewer_state
```

For a bounded file-based graphical launch, `--frames 360 --screenshot build/viewer.png` closes
after rendering 360 frames and captures the final framebuffer. This still requires
a graphical desktop. Backward stepping works after COMPLETE and rebuilds a fresh
viewer and fusion state by replaying the exact prefix from the beginning, including
resets, retirements and histories. Recordings are loaded in memory; live stdin, arbitrary seeking and
precomputed global-track JSONL input are not part of this initial viewer.

For a bounded launch without a file, the wrapper requires its forwarding separator:
`python scripts/dev.py viewer -- --frames 3 --screenshot build/viewer-controls.png`.
The focused viewer tests also compare UI-prepared recording bytes with the existing
run/record path, verify repeatability and both seed changes, and check input limits
and playback navigation. Workflow tests cover file and no-file command routing.
