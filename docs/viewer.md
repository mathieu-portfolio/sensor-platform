# Event-driven recording viewer

`sensor_platform_viewer` is an optional raylib executable. It reads an existing
complete format-v1 `.events` recording through `readRecording`, validates it before
opening the window, and feeds recorded events to the existing `FusionSystem` with
its default configuration. It does not link the platform runner, create a world,
advance physics, or sample sensors. Graphical dependencies link only to the viewer;
viewer state and its tests remain headless. No event format or core changes are needed.

## Build and open

Install raylib 5.5 or newer separately and make its CMake package discoverable (`raylib_DIR`
or an existing toolchain). There is no implicit download. The viewer defaults OFF.
From sensor-platform, reuse an appropriate existing build directory:

```sh
python scripts/dev.py --build-dir build/consumer-verified build --target sensor_platform_viewer -- -DSENSOR_PLATFORM_VIEWER=ON -Draylib_DIR=<installed-raylib-cmake-directory>
build/consumer-verified/Debug/sensor_platform_viewer.exe build/sample.events
```

Use your generator's binary path (single-config builds omit `Debug/`). On Windows
with shared raylib, its runtime DLLs must be beside the executable or on `PATH`.
An existing default sample recording can additionally show sensor geometry:

```sh
build/consumer-verified/Debug/sensor_platform_viewer.exe build/sample.events --layout docs/sample.sensors.layout
```

The layout is only an explicit annotation for that sample; never apply it to an
unrelated recording. The viewer does not infer sensor configuration or truth from
measurement positions. Without a layout it labels geometry unavailable.

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
- Space pauses/resumes; Right consumes one event and pauses; R restarts playback.
  +/- changes speed (default 0.25x), mouse wheel zooms, left drag pans and F fits.
  Escape closes. Completion holds the final frame; there is no simulation update
  or additional fusion prediction between recorded events.

Playback preserves source order and relative acquisition times. Equal-time events
are delivered together during timed playback. Run resets concatenate generation
timelines without inventing an unknown inter-generation delay. Right-arrow stepping
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

For a bounded graphical launch, `--frames 360 --screenshot build/viewer.png` closes
after rendering 360 frames and captures the final framebuffer. This still requires
a graphical desktop. Recordings are loaded in memory; live stdin, seeking and
precomputed global-track JSONL input are not part of this initial viewer.
