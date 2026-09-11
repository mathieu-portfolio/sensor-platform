"""Seed selection and deterministic aggregation of the existing evaluator's results."""
import argparse
import math

METRICS = ("position_rmse", "missed_target_samples", "false_track_samples", "unique_false_tracks", "id_switches")
MAX_SEED = 2**32 - 4  # Scenario generation adds sensor IDs to the seed.


def seed(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("seed must be an integer") from None
    if not 0 <= number <= MAX_SEED:
        raise argparse.ArgumentTypeError(f"seed must be in 0..{MAX_SEED}")
    return number


def seed_list(value):
    values = [seed(item) for item in value.split(",")]
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError("duplicate seeds are not allowed")
    return sorted(values)


def summarize(scenario, results):
    rows = [dict(seed=result["seed"], **{key: result[key] for key in METRICS})
            for result in sorted(results, key=lambda result: result["seed"])]
    if not rows or len({row["seed"] for row in rows}) != len(rows):
        raise ValueError("expected nonempty results with unique seeds")
    aggregate = {}
    for key in METRICS:
        values = [row[key] for row in rows if row[key] is not None]
        aggregate[key] = dict(valid_seeds=len(values), mean=math.fsum(values)/len(values) if values else None,
                              min=min(values) if values else None, max=max(values) if values else None)
    return dict(schema_version=1, scenario=scenario, seeds=[row["seed"] for row in rows],
                per_seed=rows, aggregate=aggregate)
