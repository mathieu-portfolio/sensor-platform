"""Run with python -m unittest discover -s analytics/tests -v."""
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from analytics.dataset import export_run, open_dataset, SQL_DIR
from analytics.events import read_unique

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("SENSOR_PLATFORM_RUNTIME", ROOT / "build/consumer-verified/Debug/sensor_platform.exe"))
if not RUNTIME.is_absolute():
    RUNTIME = RUNTIME.resolve()


def fixture(run_id=101):
    return f"""SENSOR_EVENTS 1
RUN_STARTED {run_id} 0 1 0
SENSOR_STARTED {run_id} 0 2 0 7 0 123
SENSOR_STARTED {run_id} 0 3 0 9 0 456
MEASUREMENTS {run_id} 0 4 0 7 0 1 1 1 0.123456789 -12345.6789 0.123456789 0.00000123456789
MEASUREMENTS {run_id} 0 5 0 9 0 1 0
SENSOR_RESET {run_id} 0 6 0.25 7 1
MEASUREMENTS {run_id} 0 7 0.25 7 1 1 1 1 -2.5 3.25 0.5 2
MEASUREMENTS {run_id} 0 8 0.5 9 0 2 1 1 105 0 0.75 42
RUN_RESET {run_id} 1 9 0
SENSOR_STARTED {run_id} 1 10 0 7 0 123
SENSOR_STARTED {run_id} 1 11 0 9 0 456
MEASUREMENTS {run_id} 1 12 0 7 0 1 0
MEASUREMENTS {run_id} 1 13 0 9 0 1 1 1 100 0 0.8 24
RUN_FINISHED {run_id} 1 14 1
"""


def f32(value):
    return struct.unpack("<f", struct.pack("<f", value))[0]


class HistoricalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sensor-analytics-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dataset = self.root / "data"
        self.source = self.root / "run.events"
        self.source.write_text(fixture(), encoding="ascii")

    def export(self):
        return export_run(self.source, self.dataset, RUNTIME)

    def test_fields_resets_and_empty_scans(self):
        result = self.export()
        self.assertEqual(result["rows"], {"events": 14, "scans": 6, "measurements": 4})
        with open_dataset(self.dataset) as db:
            row = db.execute("SELECT * FROM measurements WHERE stream_sequence=4").fetchone()
            self.assertEqual(row, (101, 0, 4, 0.0, 7, 0, 1, 1,
                                   f32(0.123456789), f32(-12345.6789),
                                   f32(0.123456789), f32(0.00000123456789)))
            self.assertEqual(db.execute("SELECT run_generation,sensor_generation,scan_sequence,detection_id "
                                        "FROM measurements WHERE sensor_id=7 ORDER BY stream_sequence").fetchall(),
                             [(0, 0, 1, 1), (0, 1, 1, 1)])
            self.assertEqual(db.execute("SELECT run_generation,sensor_id,scan_sequence,measurement_count "
                                        "FROM scans WHERE measurement_count=0 ORDER BY stream_sequence").fetchall(),
                             [(0, 9, 1, 0), (1, 7, 1, 0)])
            self.assertEqual(db.execute("SELECT event_type,sensor_id,seed FROM events "
                                        "WHERE stream_sequence=3").fetchone(), ("SENSOR_STARTED", 9, 456))
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE sensor_id IS NULL").fetchone()[0], 3)
            columns = [row[0] for row in db.execute("DESCRIBE measurements").fetchall()]
            self.assertNotIn("sourceEntityId", columns)
            self.assertNotIn("truth", columns)
            self.assertEqual(db.execute("SELECT sum(measurement_count) FROM scans").fetchone()[0],
                             db.execute("SELECT count(*) FROM measurements").fetchone()[0])

    def test_multiple_runs_and_uint64_identity(self):
        self.export()
        self.source.write_text(fixture(2**64 - 1), encoding="ascii")
        self.export()
        self.assertEqual(len(list(self.dataset.glob("run_id=*/*.parquet"))), 6)
        with open_dataset(self.dataset) as db:
            self.assertEqual(db.execute("SELECT DISTINCT run_id FROM scans ORDER BY run_id").fetchall(),
                             [(101,), (2**64 - 1,)])
            self.assertEqual(db.execute("SELECT count(*) FROM measurements").fetchone()[0], 8)

    def test_duplicate_events_and_reingestion_are_idempotent(self):
        self.export()
        before = {p.name: p.read_bytes() for p in (self.dataset / "run_id=101").iterdir()}
        lines = fixture().splitlines()
        lines.insert(5, lines[4])  # repeated scan event
        lines.append(lines[-1])  # repeated finish event
        self.source.write_text("\n".join(lines) + "\n", encoding="ascii")
        result = self.export()
        self.assertEqual(result["status"], "unchanged")
        self.assertEqual(result["duplicates_removed"], 2)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.dataset / "run_id=101").iterdir()})
        # An initially duplicated input must create exactly the same dataset content.
        fresh = self.root / "fresh"
        result = export_run(self.source, fresh, RUNTIME)
        self.assertEqual(result["rows"], {"events": 14, "scans": 6, "measurements": 4})
        with open_dataset(fresh) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 14)

    def test_conflicting_duplicates_and_run_reuse_fail_without_changes(self):
        self.export()
        partition = self.dataset / "run_id=101"
        before = {p.name: p.read_bytes() for p in partition.iterdir()}
        conflict = fixture() + fixture().splitlines()[4].replace("0.123456789", "0.2") + "\n"
        self.source.write_text(conflict, encoding="ascii")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            self.export()
        self.source.write_text(fixture().replace("105 0 0.75 42", "106 0 0.75 42"), encoding="ascii")
        with self.assertRaisesRegex(ValueError, "already exists with different"):
            self.export()
        self.assertEqual(before, {p.name: p.read_bytes() for p in partition.iterdir()})

    def test_malformed_input_never_publishes(self):
        bad_inputs = [
            fixture().replace("SENSOR_EVENTS 1", "SENSOR_EVENTS 2"),
            fixture().rsplit("RUN_FINISHED", 1)[0],
            fixture().replace("MEASUREMENTS 101 0 8 0.5 9 0 2", "MEASUREMENTS 101 0 8 0.5 9 0 3"),
            fixture().replace("105 0 0.75 42", "105 nan 0.75 42"),
            fixture().replace("105 0 0.75 42", "105 0 0.75"),
            fixture().replace("RUN_STARTED 101 0 1", "RUN_STARTED 101 0 2"),
        ]
        for data in bad_inputs:
            with self.subTest(data=data[-60:]):
                self.source.write_text(data, encoding="ascii")
                with self.assertRaises(ValueError):
                    self.export()
                self.assertFalse(self.dataset.exists())

    def test_zero_scan_and_all_empty_files_keep_schema(self):
        self.source.write_text("SENSOR_EVENTS 1\nRUN_STARTED 202 0 1 0\n"
                               "SENSOR_STARTED 202 0 2 0 1 0 0\nRUN_FINISHED 202 0 3 0\n", encoding="ascii")
        self.export()
        with open_dataset(self.dataset) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM scans").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT count(*) FROM measurements").fetchone()[0], 0)
            result = db.execute((SQL_DIR / "sensor_summary.sql").read_text()).fetchone()
            self.assertEqual(result, (202, 0, 1, 0, 0, 0, None, None))

    def test_sql_respects_reset_boundaries_and_counts(self):
        self.export()
        with open_dataset(self.dataset) as db:
            rows = db.execute((SQL_DIR / "scan_cadence.sql").read_text()).fetchall()
            for row in rows:
                if row[1:4] == (0, 9, 0):
                    self.assertEqual(row[4:], (2, 0.5, 0.5, 0.5, 2.0))
                else:
                    self.assertEqual(row[4:], (1, None, None, None, None))
            summary = db.execute((SQL_DIR / "sensor_summary.sql").read_text()).fetchall()
            self.assertEqual(summary[1], (101, 0, 9, 2, 1, 1, 50.0, 0.5))
            self.assertEqual(summary[2], (101, 1, 7, 1, 0, 1, 100.0, 0.0))
            # Every example query runs on a fixture different from the default sample.
            for sql in SQL_DIR.glob("*.sql"):
                if sql.name != "schema.sql":
                    self.assertTrue(db.execute(sql.read_text()).fetchall(), sql.name)

    def test_corrupt_partition_detected_on_query_and_repeat_import(self):
        self.export()
        parquet = self.dataset / "run_id=101/scans.parquet"
        parquet.write_bytes(parquet.read_bytes()[:-8])
        with self.assertRaisesRegex(ValueError, "integrity"):
            open_dataset(self.dataset)
        with self.assertRaisesRegex(ValueError, "integrity"):
            self.export()

    def test_actual_three_radar_run(self):
        subprocess.run([str(RUNTIME), "run", "--run-id", "42", "--record", str(self.source)],
                       stdout=subprocess.DEVNULL, check=True)
        self.export()
        events, _, _, _ = read_unique(self.source)
        source_scans = [e for e in events if e.kind == "MEASUREMENTS"]
        with open_dataset(self.dataset) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], len(events))
            self.assertEqual(db.execute("SELECT count(*) FROM scans").fetchone()[0], len(source_scans))
            self.assertEqual(db.execute("SELECT count(*) FROM measurements").fetchone()[0],
                             sum(len(e.detections) for e in source_scans))
            summary = db.execute((SQL_DIR / "sensor_summary.sql").read_text()).fetchall()
            self.assertEqual([(row[2], row[3], row[4]) for row in summary], [(1, 2, 2), (2, 3, 3), (3, 5, 6)])


if __name__ == "__main__":
    unittest.main()
