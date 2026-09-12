"""Incremental local ingestion: immutable original recordings -> normalized clean runs."""
import hashlib
import json
from pathlib import Path
import tempfile

from .dataset import digest, materialize_run, validate_recording, verify_partition
from .quality import CHECKS, reconcile, source_counts


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def clean_partition(dataset, receipt):
    partition = dataset / "clean" / f"run_id={receipt['run_id']}"
    if not partition.exists():
        return None
    manifest = verify_partition(partition)
    if manifest["source_sha256"] != receipt["normalized_sha256"]:
        raise ValueError(f"run {receipt['run_id']} already exists with different events; assign a new run ID")
    return manifest


def raw_receipt(raw, identity):
    receipt = json.loads((raw / "manifest.json").read_text(encoding="utf-8"))
    if receipt["schema_version"] != 1 or receipt["recording_sha256"] != identity or digest(raw / "source.events") != identity:
        raise ValueError(f"raw recording integrity check failed: {raw}")
    return receipt


def ingest_recording(source, dataset, runtime):
    source, dataset = Path(source), Path(dataset)
    # Snapshot the bytes once, so validation and archival see exactly the same input.
    original = source.read_bytes()
    identity = hashlib.sha256(original).hexdigest()
    raw = dataset / "raw" / f"sha256={identity}"
    existed = raw.exists()
    if not existed:
        receipt = dict(schema_version=1, recording_sha256=identity, source_name=source.name)
        raw.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ingest-", dir=raw.parent) as temporary:
            staging = Path(temporary)
            (staging / "source.events").write_bytes(original)
            write_json(staging / "manifest.json", receipt)
            write_json(staging / "quality.json", dict(schema_version=1, recording_sha256=identity,
                                                      status="pending", stage="validation"))
            staging.rename(raw)
    receipt = raw_receipt(raw, identity)
    report_path = raw / "quality.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    if report.get("status") == "rejected":
        raise ValueError(report["error"])
    if report.get("status") == "passed":
        manifest = clean_partition(dataset, receipt)
        if manifest is not None:
            reconcile(dataset / "clean" / f"run_id={receipt['run_id']}", report["source_rows"])
            return dict(status="unchanged", recording_sha256=identity, run_id=receipt["run_id"], rows=manifest["rows"])

    report = dict(schema_version=1, recording_sha256=identity, status="pending", stage="validation")
    try:
        events, normalized_hash, duplicates = validate_recording(raw / "source.events", runtime)
        receipt.update(normalized_sha256=normalized_hash, run_id=events[0].run_id,
                       duplicates_removed=duplicates)
        write_json(raw / "manifest.json", receipt)
        report.update(run_id=events[0].run_id, normalized_sha256=normalized_hash,
                      duplicates_removed=duplicates, checks_passed=CHECKS,
                      source_rows=source_counts(events), stage="publication")
        write_json(report_path, report)
        result = materialize_run(events, normalized_hash, duplicates, dataset / "clean")
        report.update(status="passed", stage="complete", clean_rows=result["rows"],
                      checks_passed=CHECKS + ["clean_reconciliation"])
        write_json(report_path, report)
    except Exception as error:
        # Data errors are quarantined; infrastructure failures remain retryable.
        report.update(status="rejected" if isinstance(error, ValueError) else "error",
                      error=str(error), error_type=type(error).__name__)
        write_json(report_path, report)
        raise
    status = "recovered" if existed else ("imported" if result["status"] == "created" else "archived")
    return dict(status=status, recording_sha256=identity, run_id=result["run_id"], rows=result["rows"])


def ingest(source, dataset, runtime):
    """A file or a sorted, nonrecursive inbox of *.events files. One writer per dataset."""
    source = Path(source)
    sources = sorted(p for p in source.glob("*.events") if p.is_file()) if source.is_dir() else [source]
    imports = [ingest_recording(path, dataset, runtime) for path in sources]
    return dict(imports=imports, new_runs=sum(row["status"] in ("imported", "recovered") for row in imports),
                new_recordings=sum(row["status"] in ("imported", "archived") for row in imports),
                unchanged=sum(row["status"] == "unchanged" for row in imports))
