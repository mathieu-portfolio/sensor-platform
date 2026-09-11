"""Small analytic trajectories with seeded observations; not a radar fidelity model."""
import json
import random
import struct

NAMES = ("overlap", "asynchronous", "outage_noise", "crossing")


def f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def generate(name, directory, seed=42):
    if name not in NAMES:
        raise ValueError("unknown evaluation scenario")
    directory.mkdir(parents=True, exist_ok=False)
    run_id = 1001 + NAMES.index(name)
    sensors = [1, 2] if name in ("overlap", "crossing") else [1, 2, 3]
    rng = {sensor: random.Random(seed + sensor) for sensor in sensors}
    scans = dict.fromkeys(sensors, 0)
    detections = dict.fromkeys(sensors, 0)
    lines, truth = ["SENSOR_EVENTS 1"], []
    sequence = 0

    def emit(kind, time, fields=""):
        nonlocal sequence
        sequence += 1
        lines.append(f"{kind} {run_id} 0 {sequence} {f32(time):.9g}" + (" " + fields if fields else ""))

    emit("RUN_STARTED", 0)
    for sensor in sensors:
        emit("SENSOR_STARTED", 0, f"{sensor} 0 {seed+sensor}")
    times = [0, .25, 1.5, 1.75, 2] if name == "crossing" else [tick/8 for tick in range(65)]
    for tick, time in enumerate(times):
        entities = [dict(truth_id="A", x=-4+4*time, y=0), dict(truth_id="B", x=4-4*time, y=0)] if name == "crossing" else [dict(truth_id="A", x=2*time, y=5)]
        emitted = False
        for sensor in sensors:
            period = 2 if name == "overlap" else {1: 4, 2: 2, 3: 1}[sensor]
            if name != "crossing" and tick % period:
                continue
            if name == "outage_noise" and sensor == 2 and 2 <= time < 5:
                continue
            observations = []
            for entity in entities:
                if name == "outage_noise" and rng[sensor].random() < .15:
                    continue
                noise = .7 if name == "outage_noise" else 0
                observations.append((f32(entity["x"] + rng[sensor].gauss(0, noise)),
                                     f32(entity["y"] + rng[sensor].gauss(0, noise))))
            # A persistent false return confirms briefly; truth has no corresponding target.
            if name == "outage_noise" and sensor == 1 and 1 <= time <= 2:
                observations.append((100, 80))
            fields = []
            for x, y in observations:
                detections[sensor] += 1
                fields += [str(detections[sensor]), f"{x:.9g}", f"{y:.9g}", "0.8", "2"]
            scans[sensor] += 1
            emit("MEASUREMENTS", time, f"{sensor} 0 {scans[sensor]} {len(observations)} " + " ".join(fields))
            emitted = True
        if emitted:
            # Evaluate only after all sensors at a timestamp: avoid over-weighting dense sensors.
            truth.append(dict(run_id=run_id, run_generation=0, source_sequence=sequence,
                              acquisition_time=f32(time), entities=entities))
    emit("RUN_FINISHED", times[-1])
    (directory / "measurements.events").write_text("\n".join(lines) + "\n", encoding="ascii")
    (directory / "truth.jsonl").write_text("".join(json.dumps(row) + "\n" for row in truth))
    (directory / "scenario.json").write_text(json.dumps(dict(name=name, seed=seed, run_id=run_id,
                                                              generator_version=1, frame="world Cartesian", duration=times[-1]), indent=2))
