"""Decode format v1 into tables; delegate lifecycle/order validation to the C++ replay path."""
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import math
from pathlib import Path
import re
import struct

HEADER = "SENSOR_EVENTS 1"
FLOAT = re.compile(r"-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


@dataclass(frozen=True)
class Event:
    kind: str
    run_id: int
    generation: int
    sequence: int
    time: float
    sensor_id: int | None = None
    sensor_generation: int | None = None
    scan_sequence: int | None = None
    seed: int | None = None
    detections: tuple = ()

    def line(self):
        fields = [self.kind, self.run_id, self.generation, self.sequence, format(self.time, ".9g")]
        if self.kind in ("SENSOR_STARTED", "SENSOR_RESET", "MEASUREMENTS"):
            fields += [self.sensor_id, self.sensor_generation]
        if self.kind == "SENSOR_STARTED":
            fields.append(self.seed)
        if self.kind == "MEASUREMENTS":
            fields += [self.scan_sequence, len(self.detections)]
            for identity, *values in self.detections:
                fields += [identity, *(format(value, ".9g") for value in values)]
        return " ".join(map(str, fields)) + "\n"

    def rows(self):
        common = (self.run_id, self.generation, self.sequence, self.time)
        event = common + (self.kind, self.sensor_id, self.sensor_generation,
                          self.scan_sequence, len(self.detections) if self.kind == "MEASUREMENTS" else None,
                          self.seed)
        if self.kind != "MEASUREMENTS":
            return event, None, ()
        scan_key = common + (self.sensor_id, self.sensor_generation, self.scan_sequence)
        return event, scan_key + (len(self.detections),), tuple(scan_key + d for d in self.detections)


def parse(line):
    tokens = line.split()
    if not tokens:
        raise ValueError("empty event line")
    kind, *tokens = tokens
    position = 0

    def token():
        nonlocal position
        if position == len(tokens):
            raise ValueError("missing field")
        value = tokens[position]
        position += 1
        return value

    def integer(bits=64, signed=False):
        value = token()
        if not re.fullmatch(r"-?[0-9]+" if signed else r"[0-9]+", value):
            raise ValueError("invalid integer")
        result = int(value)
        low, high = (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1) if signed else (0, 2**bits - 1)
        if not low <= result <= high:
            raise ValueError("integer out of range")
        return result

    def number():
        value = token()
        if not FLOAT.fullmatch(value):
            raise ValueError("invalid float")
        try:
            result = struct.unpack("<f", struct.pack("<f", float(value)))[0]
        except (OverflowError, ValueError):
            raise ValueError("float out of range") from None
        if not math.isfinite(result) or (result == 0 and Decimal(value) != 0):
            raise ValueError("nonfinite or underflowing float")
        # Canonicalize signed zero for identity comparison and hashing.
        return result if result else 0.0

    run_id, generation, sequence, time = integer(), integer(), integer(), number()
    sensor_id = sensor_generation = scan_sequence = seed = None
    detections = ()
    if kind in ("SENSOR_STARTED", "SENSOR_RESET", "MEASUREMENTS"):
        sensor_id, sensor_generation = integer(32, signed=True), integer()
        if kind == "SENSOR_STARTED":
            seed = integer(32)
        if kind == "MEASUREMENTS":
            scan_sequence, count = integer(), integer()
            if len(tokens) - position != count * 5:
                raise ValueError("measurement count does not match tuples")
            detections = tuple((integer(32, signed=True), number(), number(), number(), number())
                               for _ in range(count))
    elif kind not in ("RUN_STARTED", "RUN_RESET", "RUN_FINISHED"):
        raise ValueError(f"unknown event type: {kind}")
    if position != len(tokens):
        raise ValueError("extra fields")
    return Event(kind, run_id, generation, sequence, time, sensor_id,
                 sensor_generation, scan_sequence, seed, detections)


def read_unique(source: Path):
    """First occurrence wins only for identical typed payloads; conflicting identities fail."""
    events = {}
    duplicates = 0
    with source.open(encoding="ascii") as stream:
        if stream.readline().rstrip("\r\n") != HEADER:
            raise ValueError("unsupported recording header/version")
        for line_number, line in enumerate(stream, 2):
            try:
                event = parse(line)
                key = (event.run_id, event.sequence)
                if key in events:
                    if events[key] != event:
                        raise ValueError(f"conflicting duplicate event {key}")
                    duplicates += 1
                else:
                    events[key] = event
            except ValueError as error:
                raise ValueError(f"line {line_number}: {error}") from error
    if not events:
        raise ValueError("empty recording")
    normalized = HEADER + "\n" + "".join(event.line() for event in events.values())
    return list(events.values()), normalized, hashlib.sha256(normalized.encode("ascii")).hexdigest(), duplicates
