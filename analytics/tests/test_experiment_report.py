"""DuckDB must support a result set whose optional timing fields are all null."""
import json
from pathlib import Path
import tempfile
import unittest

import duckdb


class ExperimentReportTests(unittest.TestCase):
    def test_null_timing_columns(self):
        metrics = dict(total_produced=0, total_consumed=0, produced_events_per_second=None,
                       consumed_events_per_second=None, latency_p50_ms=None, latency_p95_ms=None,
                       latency_p99_ms=None, max_backlog=0, catchup_seconds=None,
                       duplicate_count=0, missing_sequence_count=1, integrity_pass=False)
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as db:
            source = Path(directory) / "summary.json"
            source.write_text(json.dumps(dict(config=dict(name="incomplete"), transport="local", metrics=metrics)))
            db.read_json(str(source)).create_view("experiments")
            sql = Path(__file__).resolve().parents[2] / "experiments/sql/comparison.sql"
            row = db.execute(sql.read_text()).fetchone()
            self.assertEqual(row, ("incomplete", "local", 0, 0, None, None, None, None, None, 0, None, 0, 1, False))
