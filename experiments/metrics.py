"""Offline reconciliation. Simulation timestamps are never used as transport clocks."""
import csv
from pathlib import Path
from analytics.events import parse


def percentile(values, percent):
    if not 0 <= percent <= 100:
        raise ValueError("percentile outside 0..100")
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lo = int(position)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (position - lo)


def read_events(path):
    events, errors = [], []
    try:
        with Path(path).open(encoding="ascii") as stream:
            if stream.readline().rstrip() != "SENSOR_EVENTS 1":
                errors.append("invalid recording header")
            for number, line in enumerate(stream, 2):
                try:
                    events.append(parse(line))
                except ValueError as error:
                    errors.append(f"line {number}: {error}")
    except (OSError, UnicodeError) as error:
        errors.append(str(error))
    return events, errors


def integrity(expected, actual):
    reference = {(e.run_id, e.sequence): e for e in expected}
    seen = {}
    duplicates = conflicts = ordering = 0
    previous = 0
    for event in actual:
        key = (event.run_id, event.sequence)
        if key in seen:
            duplicates += 1
            conflicts += seen[key] != event
        else:
            ordering += event.sequence <= previous
            previous = event.sequence
            seen[key] = event
    missing = len(reference.keys() - seen.keys())
    unexpected = len(seen.keys() - reference.keys())
    mismatched = sum(reference[key] != value for key, value in seen.items() if key in reference)
    return dict(duplicate_count=duplicates, conflicting_duplicate_count=conflicts,
                missing_sequence_count=missing, ordering_violations=ordering,
                unexpected_event_count=unexpected, payload_mismatches=mismatched,
                integrity_pass=not (duplicates or conflicts or missing or ordering or unexpected or mismatched))


def read_trace(path):
    if not Path(path).exists():
        return []
    with Path(path).open() as stream:
        return [dict(phase=r["phase"], sequence=int(r["sequence"]), wall_ns=int(r["wall_ns"]))
                for r in csv.DictReader(stream)]


def calculate(produced, consumed, expected, actual):
    result = integrity(expected, actual)
    p = {r["sequence"]: r["wall_ns"] for r in produced if r["phase"] == "produced"}
    c = {}
    for row in consumed:
        if row["phase"] == "consumed":
            c.setdefault(row["sequence"], row["wall_ns"])
    latencies = [(seq, p[seq], c[seq], (c[seq] - p[seq]) / 1e6) for seq in sorted(p.keys() & c.keys())]
    clock_errors = sum(row[3] < 0 for row in latencies)
    # Epoch clocks allow cross-process correlation, but clock steps invalidate latency/rates.
    clock_errors += sum(b["wall_ns"] < a["wall_ns"] for rows in (produced, consumed)
                        for a, b in zip(rows, rows[1:]))
    # Exact client-side outstanding count at each timestamp; includes in-flight publish/output.
    timeline = sorted([(t, 0, seq) for seq, t in p.items()] + [(t, 1, seq) for seq, t in c.items()])
    outstanding, processed = set(), set()
    backlog_samples = []
    for timestamp, phase, seq in timeline:
        if phase == 0 and seq not in processed:
            outstanding.add(seq)
        elif phase == 1:
            processed.add(seq)
            outstanding.discard(seq)
        backlog_samples.append((timestamp, len(outstanding)))
    resumes = [r["wall_ns"] for r in consumed if r["phase"] == "resume"]
    catchup = None
    if resumes:
        resume = resumes[-1]
        lag_at_resume = next((lag for timestamp, lag in reversed(backlog_samples) if timestamp <= resume), 0)
        caught = resume if lag_at_resume == 0 else next((t for t, lag in backlog_samples if t >= resume and lag == 0), None)
        if caught is not None:
            catchup = (caught - resume) / 1e9
    def rate(times):
        # n-1 inter-arrivals over first-to-last interval, excluding process startup/teardown.
        return (len(times)-1) * 1e9 / (max(times)-min(times)) if len(times) > 1 and max(times) > min(times) else None
    values = [r[3] for r in latencies]
    trace_pass = (set(p) == {e.sequence for e in expected} and set(c) == {e.sequence for e in actual}
                  and len(p) == len(produced) and len(c) == sum(r["phase"] == "consumed" for r in consumed))
    result.update(total_produced=len(p), total_consumed=sum(r["phase"] == "consumed" for r in consumed),
                  produced_events_per_second=rate(list(p.values())), consumed_events_per_second=rate(list(c.values())),
                  latency_p50_ms=percentile(values, 50), latency_p95_ms=percentile(values, 95),
                  latency_p99_ms=percentile(values, 99), max_backlog=max((b for _, b in backlog_samples), default=0),
                  final_backlog=len(outstanding), catchup_seconds=catchup, pause_observed=bool(resumes),
                  clock_errors=clock_errors, trace_integrity_pass=trace_pass,
                  integrity_pass=result["integrity_pass"] and trace_pass and not clock_errors)
    return result, latencies, backlog_samples
