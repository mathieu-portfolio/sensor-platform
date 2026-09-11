"""Concrete JSON configuration, resolved deterministically into a numeric C++ plan."""
import math
import struct

DEFAULTS = dict(name="baseline", run_id=101, duration_seconds=2, tick_hz=80,
                wall_seconds_per_sim_second=1, sensor_count=3, scan_hz=[4, 8, 16], seed=42,
                consumer_delay_ms=0, consumer_start_delay_ms=0, pause_after_events=0,
                pause_ms=0, outage=None)


def simulation_float(value):
    return struct.unpack("f", struct.pack("f", value))[0]


def resolve(raw):
    unknown = raw.keys() - DEFAULTS.keys()
    if unknown:
        raise ValueError(f"unknown configuration fields: {sorted(unknown)}")
    config = DEFAULTS | raw
    for key, low, high in [("run_id", 1, 2**64-1), ("sensor_count", 1, 1000),
                           ("tick_hz", 1, 10000), ("seed", 0, 2**32-1),
                           ("consumer_delay_ms", 0, 60000), ("consumer_start_delay_ms", 0, 60000),
                           ("pause_after_events", 0, 10000000), ("pause_ms", 0, 60000)]:
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise ValueError(f"invalid {key}")
    for key, low, high in [("duration_seconds", 0.001, 3600), ("wall_seconds_per_sim_second", 0, 100)]:
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"invalid {key}")
    ticks = config["duration_seconds"] * config["tick_hz"]
    if not math.isclose(ticks, round(ticks), abs_tol=1e-8) or not 1 <= ticks <= 10000000:
        raise ValueError("duration must be an integral number of ticks, at most 10000000")
    if not isinstance(config["name"], str) or not config["name"]:
        raise ValueError("name must be nonempty")
    rates = config["scan_hz"]
    if not isinstance(rates, list) or not rates or any(type(hz) not in (int, float) or
            not math.isfinite(hz) or not 0 < hz <= config["tick_hz"] for hz in rates):
        raise ValueError("scan_hz must contain positive rates no greater than tick_hz")
    if bool(config["pause_after_events"]) != bool(config["pause_ms"]):
        raise ValueError("pause_after_events and pause_ms must both be set")
    outage = config["outage"]
    if outage is not None:
        if not isinstance(outage, dict) or set(outage) != {"sensor_id", "start", "end"}:
            raise ValueError("outage requires sensor_id, start, end")
        if type(outage["sensor_id"]) is not int or not 1 <= outage["sensor_id"] <= config["sensor_count"]:
            raise ValueError("unknown outage sensor")
        if any(type(outage[k]) not in (int, float) or not math.isfinite(outage[k]) for k in ("start", "end")) or not 0 <= outage["start"] < outage["end"] <= config["duration_seconds"]:
            raise ValueError("invalid outage interval")
        # Match the core's float32 acquisition-time comparisons, including decimal boundaries.
        if simulation_float(outage["start"]) >= simulation_float(outage["end"]):
            raise ValueError("outage interval collapses at float32 precision")
    return config


def plan(config, paced=True):
    scale = config["wall_seconds_per_sim_second"] if paced else 0
    lines = ["SENSOR_EXPERIMENT 1", f"{round(config['duration_seconds'] * config['tick_hz'])} {config['tick_hz']} {scale}"]
    for index in range(config["sensor_count"]):
        # Stable per-ID seeds; adding sensors does not alter existing streams.
        seed = (config["seed"] + index * 2654435761) % 2**32
        lines.append(f"SENSOR {index+1} {index % 10 * 10} {index // 10 * 10} {config['scan_hz'][index % len(config['scan_hz'])]} {seed}")
    if config["outage"]:
        o = config["outage"]
        lines.append(f"OUTAGE {o['sensor_id']} {o['start']} {o['end']}")
    return "\n".join(lines) + "\n"
