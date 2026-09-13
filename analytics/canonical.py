"""Canonical descriptive SQL analyses of an existing, immutable sweep dataset."""
import argparse
import csv
import json
from pathlib import Path
import sys

import duckdb

from .dataset import digest
from .publication import staging_directory

SQL = Path(__file__).parent / "sql/canonical/statistics.sql"
ANALYSES = ("noise", "reliability", "clutter", "convergence", "sensor_network")
NOTES = [
    "Descriptive equal-weight run summaries across scenario seeds; no significance or causal claims.",
    "Every other procedural parameter, layout seed and evaluation setting defines a separate condition; experiments are never pooled.",
    "stddev is sample standard deviation (null for fewer than two valid runs). Null metrics are excluded, with valid_count and null_count reported.",
    "Measurement yield includes clutter. False sensor-return labels are unavailable in stored sweeps; false-track metrics must not be interpreted as false returns.",
    "A single parameter level cannot establish a parameter relationship. Inspect fixed controls and seed lists before comparing conditions.",
]


def write_csv(relation, path):
    result = relation.execute()
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(c[0] for c in result.description)
        writer.writerows(result.fetchall())


def analyze(source, output=None):
    source = Path(source).resolve()
    output = Path(output).resolve() if output is not None else source / "canonical_analysis"
    if output.exists():
        raise FileExistsError(f"analysis output exists: {output}; choose a new directory")
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("run_count", 0) < 1:
        raise ValueError("unsupported or empty sweep manifest")
    hashes = {t: digest(source / f"{t}.parquet") for t in ("experiments", "experiment_metrics")}
    if hashes != manifest["files"]:
        raise ValueError("sweep table checksum mismatch")
    with duckdb.connect() as db:
        for table in hashes:
            db.read_parquet(str(source / f"{table}.parquet"), hive_partitioning=False).create_view(table)
            counts = db.execute(f"SELECT count(*),count(DISTINCT run_id),count(DISTINCT experiment_id) FROM {table}").fetchone()
            if counts != (manifest["run_count"], manifest["run_count"], 1):
                raise ValueError("duplicate or missing sweep run identities")
            if db.execute(f"SELECT count(*) FROM {table} WHERE experiment_id IS DISTINCT FROM ? OR experiment_name IS DISTINCT FROM ? OR seed IS NULL", [manifest["experiment_id"], manifest["name"]]).fetchone()[0]:
                raise ValueError("sweep experiment identity mismatch")
        db.execute(SQL.read_text(encoding="utf-8"))
        if db.table("individual_runs").count("*").fetchone()[0] != manifest["run_count"]:
            raise ValueError("experiment/metric run membership mismatch")
        if db.execute("SELECT count(*) FROM individual_runs WHERE seed IS DISTINCT FROM scenario_seed").fetchone()[0]:
            raise ValueError("scenario seed mismatch")
        if db.execute("SELECT count(*) FROM (SELECT condition_id,seed FROM individual_runs GROUP BY ALL HAVING count(*)>1)").fetchone()[0]:
            raise ValueError("duplicate seed within condition")
        if db.execute("SELECT count(*) FROM run_values WHERE value IS NOT NULL AND NOT isfinite(value)").fetchone()[0]:
            raise ValueError("nonfinite metric")
        # Each metric in each analysis accounts for every input run exactly once.
        if db.execute("SELECT count(*) FROM (SELECT analysis,metric FROM canonical_statistics GROUP BY ALL HAVING sum(run_count) != ?)", [manifest["run_count"]]).fetchone()[0]:
            raise ValueError("aggregate run count mismatch")
        summary = dict(schema_version=1, experiment_id=manifest["experiment_id"], name=manifest["name"],
                       run_count=manifest["run_count"], source_files=hashes,
                       source_runtime_sha256=manifest.get("runtime_sha256"),
                       sql_sha256=digest(SQL), duckdb_version=duckdb.__version__, notes=NOTES,
                       condition_count=db.execute("SELECT count(DISTINCT condition_id) FROM individual_runs").fetchone()[0],
                       parameter_levels={p: [r[0] for r in db.execute(f"SELECT DISTINCT {p} FROM individual_runs ORDER BY {p}").fetchall()]
                                         for p in ("noise", "reliability", "clutter", "convergence", "sensor_count", "coverage")})
        output.parent.mkdir(parents=True, exist_ok=True)
        with staging_directory(output.parent) as staging:
            SQL_copy = staging / "statistics.sql"
            SQL_copy.write_bytes(SQL.read_bytes())
            db.table("individual_runs").order("experiment_id,run_id").write_parquet(str(staging / "individual_runs.parquet"), compression="zstd")
            write_csv(db.table("metric_definitions").order("metric"), staging / "metric_definitions.csv")
            for analysis in ANALYSES:
                result = db.sql("SELECT * FROM canonical_statistics WHERE analysis = ? ORDER BY condition,metric", params=[analysis])
                result.write_parquet(str(staging / f"{analysis}.parquet"), compression="zstd")
                write_csv(result, staging / f"{analysis}.csv")
            summary["files"] = {p.name: digest(p) for p in sorted(staging.iterdir())}
            (staging / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
            staging.rename(output)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="existing sweep root (experiments.parquet and experiment_metrics.parquet)")
    parser.add_argument("--output", type=Path, help="new output directory; default: DATASET/canonical_analysis")
    args = parser.parse_args(argv)
    try:
        result = analyze(args.dataset, args.output)
        print(json.dumps({k: result[k] for k in ("name", "run_count", "condition_count", "parameter_levels")}, sort_keys=True))
        return 0
    except Exception as error:
        print(f"analysis: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
