import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analytics.dataset import open_dataset
from analytics.ingestion import ingest

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = Path(os.environ.get("SENSOR_PLATFORM_RUNTIME", ROOT / "build/consumer-verified/Debug/sensor_platform.exe")).resolve()


def recording(run=1):
    return (f"SENSOR_EVENTS 1\r\nRUN_STARTED {run} 0 1 0\r\nSENSOR_STARTED {run} 0 2 0 1 0 42\r\n"
            f"MEASUREMENTS {run} 0 3 0 1 0 1 1 1 1.2500 2.5 0.8 3\r\n"
            f"MEASUREMENTS {run} 0 4 0.5 1 0 2 0\r\nRUN_FINISHED {run} 0 5 1\r\n").encode("ascii")


def snapshot(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


class IngestionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        self.source = self.inbox / "one.events"
        self.source.write_bytes(recording())
        self.dataset = self.root / "dataset"

    def test_first_import_preserves_raw_bytes_and_clean_tables(self):
        result = ingest(self.inbox, self.dataset, RUNTIME)
        self.assertEqual(result["new_runs"], 1)
        identity = hashlib.sha256(recording()).hexdigest()
        raw = self.dataset / "raw" / f"sha256={identity}"
        self.assertEqual((raw / "source.events").read_bytes(), recording())
        receipt = json.loads((raw / "manifest.json").read_text())
        self.assertEqual(receipt["recording_sha256"], identity)
        self.assertEqual(receipt["duplicates_removed"], 0)
        with open_dataset(self.dataset / "clean") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0], 5)
            self.assertEqual(db.execute("SELECT measurement_count FROM scans ORDER BY stream_sequence").fetchall(), [(1,), (0,)])
            self.assertEqual(db.execute("SELECT x,y FROM measurements").fetchone(), (1.25, 2.5))

    def test_identical_reimport_skips_validation_and_conversion(self):
        ingest(self.source, self.dataset, RUNTIME)
        before = snapshot(self.dataset)
        renamed = self.root / "renamed.events"
        renamed.write_bytes(recording())
        with patch("analytics.ingestion.validate_recording", side_effect=AssertionError("unexpected validation")), \
             patch("analytics.ingestion.materialize_run", side_effect=AssertionError("unexpected conversion")), \
             patch("analytics.ingestion.export_run", side_effect=AssertionError("unexpected recovery")):
            result = ingest(renamed, self.dataset, RUNTIME)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["new_runs"], 0)
        self.assertEqual(snapshot(self.dataset), before)

    def test_incremental_import_only_adds_new_run(self):
        ingest(self.inbox, self.dataset, RUNTIME)
        before = snapshot(self.dataset)
        (self.inbox / "two.events").write_bytes(recording(2))
        result = ingest(self.inbox, self.dataset, RUNTIME)
        self.assertEqual((result["unchanged"], result["new_runs"]), (1, 1))
        after = snapshot(self.dataset)
        self.assertTrue(all(after[name] == value for name, value in before.items()))
        with open_dataset(self.dataset / "clean") as db:
            self.assertEqual(db.execute("SELECT run_id,count(*) FROM events GROUP BY run_id ORDER BY run_id").fetchall(), [(1, 5), (2, 5)])

    def test_conflicting_run_or_duplicate_is_rejected_without_archival(self):
        ingest(self.source, self.dataset, RUNTIME)
        before = snapshot(self.dataset)
        self.source.write_bytes(recording().replace(b"1.2500", b"8.5"))
        with self.assertRaisesRegex(ValueError, "different events"):
            ingest(self.source, self.dataset, RUNTIME)
        self.assertEqual(snapshot(self.dataset), before)
        self.source.write_bytes(recording() + recording().splitlines()[3].replace(b"1.2500", b"8.5") + b"\n")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            ingest(self.source, self.dataset, RUNTIME)
        self.assertEqual(snapshot(self.dataset), before)

    def test_semantically_identical_variant_is_archived_without_clean_rewrite(self):
        ingest(self.source, self.dataset, RUNTIME)
        before = snapshot(self.dataset / "clean")
        variant = recording().replace(b"\r\n", b"\n").replace(b"1.2500", b"1.25")
        variant += variant.splitlines()[3] + b"\n"  # An exact duplicate event is retained in raw.
        self.source.write_bytes(variant)
        result = ingest(self.source, self.dataset, RUNTIME)
        self.assertEqual(result["imports"][0]["status"], "archived")
        self.assertEqual((result["new_recordings"], result["new_runs"]), (1, 0))
        self.assertEqual(snapshot(self.dataset / "clean"), before)
        self.assertEqual(len(list((self.dataset / "raw").glob("sha256=*"))), 2)
        raw = self.dataset / "raw" / ("sha256=" + hashlib.sha256(variant).hexdigest())
        self.assertEqual((raw / "source.events").read_bytes(), variant)
        self.assertEqual(json.loads((raw / "manifest.json").read_text())["duplicates_removed"], 1)

    def test_retry_finishes_archived_run_after_interrupted_conversion(self):
        with patch("analytics.ingestion.materialize_run", side_effect=OSError("interrupted")):
            with self.assertRaisesRegex(OSError, "interrupted"):
                ingest(self.source, self.dataset, RUNTIME)
        self.assertFalse((self.dataset / "clean").exists())
        raw_before = snapshot(self.dataset / "raw")
        result = ingest(self.source, self.dataset, RUNTIME)
        self.assertEqual(result["imports"][0]["status"], "recovered")
        self.assertEqual(raw_before, snapshot(self.dataset / "raw"))
        self.assertTrue((self.dataset / "clean/run_id=1/manifest.json").exists())
