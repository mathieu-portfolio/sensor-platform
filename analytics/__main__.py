"""Run from sensor-platform: python -m analytics export ... / query ..."""
import argparse
import csv
import json
from pathlib import Path
import sys

from .dataset import export_run, open_dataset, SQL_DIR
from .track_events import open_tracks


def main():
    parser = argparse.ArgumentParser(description="Recording -> Parquet -> DuckDB/SQL")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="validate and materialize one completed run")
    export.add_argument("recording", type=Path)
    export.add_argument("dataset", type=Path)
    export.add_argument("--runtime", type=Path, required=True, help="sensor_platform executable for replay validation")
    query = commands.add_parser("query", help="query immutable Parquet partitions using DuckDB")
    query.add_argument("dataset", type=Path)
    query.add_argument("--sql", type=Path, default=SQL_DIR / "sensor_summary.sql")
    tracks = commands.add_parser("tracks", help="query completed global-track JSON Lines")
    tracks.add_argument("dataset", type=Path)
    tracks.add_argument("--sql", type=Path, default=SQL_DIR / "fusion/summary.sql")
    args = parser.parse_args()
    try:
        if args.command == "export":
            print(json.dumps(export_run(args.recording, args.dataset, args.runtime), sort_keys=True))
        else:
            with (open_tracks(args.dataset) if args.command == "tracks" else open_dataset(args.dataset)) as connection:
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
