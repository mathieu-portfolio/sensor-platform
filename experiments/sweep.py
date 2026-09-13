"""Small deterministic procedural parameter grids, using the existing offline pipeline."""
import argparse
from dataclasses import asdict, dataclass
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import sys

from scripts.procedural import ProceduralConfig

# Runtime SENSOR_PROCEDURAL 2 order and bounds (ProceduralScenario.hpp).
PARAMETERS = {
    "speed_min": (1, 30), "speed_max": (1, 30), "maneuver": (0, 3),
    "convergence": (0, 1), "spawn_spread": (.4, 1.5), "coverage": (.65, 1.6),
    "layout_spread": (.25, 3), "noise": (0, 5), "reliability": (.35, 1), "clutter": (0, 12),
}


@dataclass(frozen=True)
class SweepConfig(ProceduralConfig):
    speed_min: float = 14
    speed_max: float = 16
    maneuver: float = 1
    convergence: float = 1
    spawn_spread: float = 1
    coverage: float = 1
    layout_spread: float = 1
    noise: float = 1
    reliability: float = 1
    clutter: float = 1

    def __post_init__(self):
        super().__post_init__()
        for name, (low, high) in PARAMETERS.items():
            value = getattr(self, name)
            if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be finite in {low}..{high}")
            object.__setattr__(self, name, float(value))
        if self.speed_min > self.speed_max:
            raise ValueError("speed_min must not exceed speed_max")

    def text(self):
        return super().text().replace("SENSOR_PROCEDURAL 1", "SENSOR_PROCEDURAL 2") + " ".join(
            format(getattr(self, name), ".9g") for name in PARAMETERS) + "\n"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def resolve(spec):
    """Validate the complete grid before any output or subprocess is created."""
    if not isinstance(spec, dict) or set(spec) != {"version", "name", "seeds", "fixed", "vary"}:
        raise ValueError("expected version, name, seeds, fixed and vary")
    if type(spec["version"]) is not int or spec["version"] != 1 or not isinstance(spec["name"], str) or not spec["name"].strip():
        raise ValueError("expected version 1 and a nonempty experiment name")
    seeds = spec["seeds"]
    if isinstance(seeds, dict):
        if not {"start", "stop"} <= seeds.keys() or seeds.keys() - {"start", "stop", "step"}:
            raise ValueError("seed range requires start, stop, optional step (stop exclusive)")
        if any(type(v) is not int for v in seeds.values()) or seeds.get("step", 1) <= 0:
            raise ValueError("seed range requires integers and a positive step")
        seeds = range(seeds["start"], seeds["stop"], seeds.get("step", 1))
    if not isinstance(seeds, (list, range)) or not 1 <= len(seeds) <= 4096:
        raise ValueError("expected 1..4096 seeds")
    if any(type(s) is not int or not 0 <= s < 2**32 for s in seeds) or len(set(seeds)) != len(seeds):
        raise ValueError("seeds must be unique uint32 integers")
    fixed, vary = spec["fixed"], spec["vary"]
    allowed = set(asdict(SweepConfig())) - {"scenario_seed"}
    if not isinstance(fixed, dict) or not isinstance(vary, dict) or not vary:
        raise ValueError("fixed and nonempty vary must be objects")
    if (fixed.keys() | vary.keys()) - allowed or fixed.keys() & vary.keys():
        raise ValueError("unknown parameter or parameter present in both fixed and vary; use seeds for scenario_seed")
    for name, values in vary.items():
        if not isinstance(values, list) or not values or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError(f"{name} requires a nonempty numeric value list")
        if len(set(values)) != len(values):
            raise ValueError(f"duplicate values for {name}")
    count = math.prod(len(v) for v in vary.values()) * len(seeds)
    if count > 4096:
        raise ValueError("sweep exceeds 4096 runs; split into smaller specifications")
    names = sorted(vary)
    configs = []
    for values in itertools.product(*(sorted(vary[n]) for n in names)):
        for seed in sorted(seeds):
            configs.append(SweepConfig(**fixed, **dict(zip(names, values)), scenario_seed=seed))
    defaults = asdict(SweepConfig())
    defaults.update(fixed)
    normalized = dict(version=1, name=spec["name"], seeds=sorted(seeds),
                      fixed={k: asdict(configs[0])[k] for k in defaults if k != "scenario_seed" and k not in vary},
                      vary={n: sorted({asdict(c)[n] for c in configs}) for n in names})
    run_ids = [int(identity(dict(generator="procedural-v1", config=asdict(c)))[:16], 16) or 1 for c in configs]
    if len(set(run_ids)) != count:
        raise ValueError("duplicate run configurations or run ID collision")
    return normalized, list(zip(run_ids, configs))


def run_sweep(spec, output, runtime):
    from analytics.analysis import export_analysis, open_analysis
    from analytics.ingestion import ingest
    from analytics.dataset import digest
    from analytics.publication import staging_directory

    normalized, runs = resolve(spec)
    experiment_id = identity(normalized)
    output, runtime = Path(output).resolve(), Path(runtime).resolve()
    if output.exists():
        raise FileExistsError(f"output already exists: {output}; choose a new directory")
    if not runtime.is_file():
        raise FileNotFoundError(f"Build sensor_platform first: {runtime}")
    output.parent.mkdir(parents=True, exist_ok=True)
    env = {k.upper(): v for k, v in os.environ.items()} if os.name == "nt" else os.environ.copy()
    # No incomplete experiment is published. No scheduler, workers or implicit build.
    with staging_directory(output.parent) as staging:
        (staging / "spec.json").write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for index, (run_id, config) in enumerate(runs, 1):
            print(f"sweep: run {index}/{len(runs)} ({run_id})", file=sys.stderr, flush=True)
            directory = staging / "runs" / f"run_id={run_id}"
            directory.mkdir(parents=True)
            (directory / "scenario.config").write_text(config.text(), encoding="ascii")
            (directory / "config.json").write_text(canonical(asdict(config)) + "\n", encoding="utf-8")
            def execute(arguments):
                result = subprocess.run([str(runtime), *map(str, arguments)], env=env,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)
                if result.returncode:
                    raise RuntimeError(f"run {run_id}: {result.stderr.decode(errors='replace').strip()}")
            execute(["run", "--run-id", run_id, "--procedural", directory / "scenario.config",
                     "--record", directory / "recording.events", "--analysis-output", directory / "analytical"])
            execute(["fuse", directory / "recording.events", "--output", directory / "tracks.jsonl"])
            ingest(directory / "recording.events", staging / "dataset", runtime)
            export_analysis(directory / "analytical", directory / "tracks.jsonl", staging / "dataset")
        with open_analysis(staging / "dataset") as db:
            db.execute("CREATE TABLE membership(experiment_id VARCHAR, experiment_name VARCHAR, run_id UBIGINT, seed UINTEGER, requested_config VARCHAR, varying_parameters VARCHAR)")
            db.executemany("INSERT INTO membership VALUES (?,?,?,?,?,?)", [
                (experiment_id, normalized["name"], run_id, config.scenario_seed, canonical(asdict(config)),
                 canonical({n: getattr(config, n) for n in normalized["vary"]})) for run_id, config in runs])
            # Actual effective parameters come from runtime metadata, not Python defaults.
            db.execute("CREATE VIEW experiments AS SELECT m.*, r.* EXCLUDE(run_id) FROM membership m JOIN runs r USING(run_id)")
            db.execute("""CREATE VIEW experiment_metrics AS
                WITH sensing AS (
                    SELECT run_id, count(*) AS scan_count, sum(measurement_count)::UBIGINT AS measurement_count,
                           count(*) FILTER (WHERE measurement_count=0) AS empty_scan_count
                    FROM scans GROUP BY run_id)
                SELECT e.experiment_id,e.experiment_name,e.seed,m.*,s.* EXCLUDE(run_id),
                       s.scan_count / e.duration_seconds AS scans_per_second,
                       s.measurement_count / e.duration_seconds AS measurements_per_second,
                       s.measurement_count / s.scan_count AS measurements_per_scan
                FROM experiments e JOIN run_metrics m USING(run_id) JOIN sensing s USING(run_id)""")
            for table in ("experiments", "experiment_metrics"):
                if db.table(table).count("*").fetchone()[0] != len(runs):
                    raise ValueError("experiment membership/metrics count mismatch")
                db.table(table).order("run_id").write_parquet(str(staging / f"{table}.parquet"), compression="zstd")
        manifest = dict(schema_version=1, experiment_id=experiment_id, name=normalized["name"],
                        run_count=len(runs), runtime_sha256=digest(runtime),
                        files={t: digest(staging / f"{t}.parquet") for t in ("experiments", "experiment_metrics")})
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staging.rename(output)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, default=Path(__file__).parent / "configs/sensor-quality.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_sweep(json.loads(args.spec.read_text(encoding="utf-8")), args.output, args.runtime)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(f"sweep: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
