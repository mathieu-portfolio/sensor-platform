"""Run from sensor-platform: python -m analytics export ... / query ..."""
import argparse
import csv
import json
from pathlib import Path
import sys

from .dataset import export_run, open_dataset, SQL_DIR
from .track_events import open_tracks
from .ingestion import ingest


def main():
    parser = argparse.ArgumentParser(description="Recording -> Parquet -> DuckDB/SQL")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="validate and materialize one completed run")
    export.add_argument("recording", type=Path)
    export.add_argument("dataset", type=Path)
    export.add_argument("--runtime", type=Path, required=True, help="sensor_platform executable for replay validation")
    ingestion = commands.add_parser("ingest", help="incrementally archive recordings and materialize clean runs")
    ingestion.add_argument("source", type=Path, help="recording file or directory containing *.events")
    ingestion.add_argument("dataset", type=Path, help="dataset root containing raw/ and clean/")
    ingestion.add_argument("--runtime", type=Path, required=True, help="sensor_platform executable for validation")
    query = commands.add_parser("query", help="query immutable Parquet partitions using DuckDB")
    query.add_argument("dataset", type=Path)
    query.add_argument("--sql", type=Path, default=SQL_DIR / "sensor_summary.sql")
    analysis = commands.add_parser("analysis-query", help="explicitly query offline truth, tracking and clean events")
    analysis.add_argument("dataset", type=Path, help="dataset root containing clean/ and analysis/")
    analysis.add_argument("--sql", type=Path, default=SQL_DIR / "analysis_summary.sql")
    analytical_export = commands.add_parser("analysis-export", help="publish separate procedural/evaluation artifacts")
    analytical_export.add_argument("artifacts", type=Path)
    analytical_export.add_argument("tracks", type=Path)
    analytical_export.add_argument("dataset", type=Path)
    analytical_export.add_argument("--gate", type=float, default=5)
    tracks = commands.add_parser("tracks", help="query completed global-track JSON Lines")
    tracks.add_argument("dataset", type=Path)
    tracks.add_argument("--sql", type=Path, default=SQL_DIR / "fusion/summary.sql")
    args = parser.parse_args()
    try:
        if args.command == "export":
            print(json.dumps(export_run(args.recording, args.dataset, args.runtime), sort_keys=True))
        elif args.command == "ingest":
            print(json.dumps(ingest(args.source, args.dataset, args.runtime), sort_keys=True))
        elif args.command == "analysis-export":
            from .analysis import export_analysis
            print(json.dumps(export_analysis(args.artifacts, args.tracks, args.dataset, args.gate), sort_keys=True))
        else:
            reader = open_tracks if args.command == "tracks" else open_dataset
            if args.command == "analysis-query":
                from .analysis import open_analysis
                reader = open_analysis
            with reader(args.dataset) as connection:
                result = connection.execute(args.sql.read_text(encoding="utf-8"))
                writer = csv.writer(sys.stdout, lineterminator="\n")
                writer.writerow(column[0] for column in result.description)
                writer.writerows(result.fetchall())
    except Exception as error:
        print(f"analytics: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
