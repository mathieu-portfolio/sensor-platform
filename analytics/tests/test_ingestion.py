import hashlib
import json
import os
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from analytics.dataset import open_dataset
from analytics.ingestion import ingest
from analytics.events import Event

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
        report = json.loads((raw / "quality.json").read_text())
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["source_rows"], dict(events=5, scans=2, measurements=1))
        self.assertEqual(report["source_rows"], report["clean_rows"])
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
             patch("analytics.ingestion.materialize_run", side_effect=AssertionError("unexpected conversion")):
            result = ingest(renamed, self.dataset, RUNTIME)
        self.assertEqual(result["unchanged"], 1)
        self.assertEqual(result["new_runs"], 0)
        self.assertEqual(snapshot(self.dataset), before)

    def test_publication_inherits_permissions_and_can_be_removed_after_retry(self):
        mkdir = os.mkdir
        publication_modes = []

        def observe_mkdir(path, mode=0o777, *args, **kwargs):
            if Path(path).name.startswith(".ingest-"):
                publication_modes.append(mode)
            return mkdir(path, mode, *args, **kwargs)

        with patch("os.mkdir", side_effect=observe_mkdir):
            ingest(self.source, self.dataset, RUNTIME)
        # 0700 installs a private Windows ACL, even when same-user reads pass.
        self.assertEqual(publication_modes, [0o777, 0o777])
        before = snapshot(self.dataset)
        self.assertEqual(ingest(self.source, self.dataset, RUNTIME)["unchanged"], 1)
        self.assertEqual(snapshot(self.dataset), before)
        self.assertFalse(list(self.dataset.rglob(".ingest-*")))
        shutil.rmtree(self.dataset)
        self.assertFalse(self.dataset.exists())

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

    def test_conflicting_run_or_duplicate_is_preserved_without_clean_changes(self):
        ingest(self.source, self.dataset, RUNTIME)
        before = snapshot(self.dataset / "clean")
        self.source.write_bytes(recording().replace(b"1.2500", b"8.5"))
        with self.assertRaisesRegex(ValueError, "different events"):
            ingest(self.source, self.dataset, RUNTIME)
        self.assertEqual(snapshot(self.dataset / "clean"), before)
        self.source.write_bytes(recording() + recording().splitlines()[3].replace(b"1.2500", b"8.5") + b"\n")
        with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
            ingest(self.source, self.dataset, RUNTIME)
        self.assertEqual(snapshot(self.dataset / "clean"), before)
        self.assertEqual(len(list((self.dataset / "raw").glob("sha256=*/quality.json"))), 3)

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
        raw_source = next((self.dataset / "raw").glob("*/source.events"))
        raw_before = raw_source.read_bytes()
        result = ingest(self.source, self.dataset, RUNTIME)
        self.assertEqual(result["imports"][0]["status"], "recovered")
        self.assertEqual(raw_before, raw_source.read_bytes())
        self.assertTrue((self.dataset / "clean/run_id=1/manifest.json").exists())

    def test_quality_rejections_preserve_source_and_diagnostic(self):
        data = recording()
        cases = {
            "missing finish": data.rsplit(b"RUN_FINISHED", 1)[0],
            "missing start": data.replace(data.splitlines(keepends=True)[1], b""),
            "duplicate start": data.replace(b"RUN_FINISHED 1 0 5 1", b"RUN_STARTED 1 0 5 1"),
            "after finish": data + b"RUN_FINISHED 1 0 6 1\n",
            "missing sequence": data.replace(b"RUN_FINISHED 1 0 5", b"RUN_FINISHED 1 0 6"),
            "duplicate sequence": data + data.splitlines()[3].replace(b"1.2500", b"8.5") + b"\n",
            "scan sequence": data.replace(b"0.5 1 0 2 0", b"0.5 1 0 3 0"),
            "unknown sensor": data.replace(b"0.5 1 0 2 0", b"0.5 2 0 2 0"),
            "time reversal": data.replace(b"RUN_FINISHED 1 0 5 1", b"RUN_FINISHED 1 0 5 0"),
            "measurement count": data.replace(b"1 0 1 1 1 1.2500", b"1 0 1 2 1 1.2500"),
        }
        for name, invalid in cases.items():
            with self.subTest(name=name):
                self.source.write_bytes(invalid)
                with self.assertRaises(ValueError):
                    ingest(self.source, self.dataset, RUNTIME)
                raw = self.dataset / "raw" / ("sha256=" + hashlib.sha256(invalid).hexdigest())
                self.assertEqual((raw / "source.events").read_bytes(), invalid)
                report = json.loads((raw / "quality.json").read_text())
                self.assertEqual(report["status"], "rejected")
                self.assertEqual(report["stage"], "validation")
                self.assertTrue(report["error"])
                before = snapshot(raw)
                with self.assertRaises(ValueError):
                    ingest(self.source, self.dataset, RUNTIME)
                self.assertEqual(snapshot(raw), before)
        self.assertFalse(list((self.dataset / "clean").glob("run_id=*")))

    def test_reconciliation_blocks_dropped_measurements(self):
        original_rows = Event.rows

        def drop_measurements(event):
            event_row, scan_row, measurements = original_rows(event)
            return event_row, scan_row, ()

        with patch.object(Event, "rows", drop_measurements):
            with self.assertRaisesRegex(ValueError, "clean reconciliation failed"):
                ingest(self.source, self.dataset, RUNTIME)
        self.assertFalse(list((self.dataset / "clean").glob("run_id=*")))
        report = json.loads(next((self.dataset / "raw").glob("*/quality.json")).read_text())
        self.assertFalse(list(self.dataset.rglob(".ingest-*")))
        self.assertEqual(report["status"], "rejected")
        self.assertEqual(report["stage"], "publication")
        self.assertIn("actual", report["error"])

    def test_reconciliation_checks_per_scan_counts_with_equal_totals(self):
        original_rows = Event.rows

        def swap_counts(event):
            event_row, scan_row, measurements = original_rows(event)
            if scan_row:
                scan_row = scan_row[:-1] + (1 - scan_row[-1],)
            return event_row, scan_row, measurements

        with patch.object(Event, "rows", swap_counts):
            with self.assertRaisesRegex(ValueError, "inconsistent scan measurement counts"):
                ingest(self.source, self.dataset, RUNTIME)
        self.assertFalse(list((self.dataset / "clean").glob("run_id=*")))

    def test_reimport_reconciles_manifest_counts_against_parquet(self):
        ingest(self.source, self.dataset, RUNTIME)
        path = self.dataset / "clean/run_id=1/manifest.json"
        manifest = json.loads(path.read_text())
        manifest["rows"]["measurements"] = 2
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "clean reconciliation failed"):
            ingest(self.source, self.dataset, RUNTIME)
