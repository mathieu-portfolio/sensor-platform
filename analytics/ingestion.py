"""Incremental local ingestion: immutable original recordings -> normalized clean runs."""
import hashlib
import json
from pathlib import Path
import tempfile

from .dataset import digest, export_run, materialize_run, validate_recording, verify_partition


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
    if raw.exists():
        receipt = raw_receipt(raw, identity)
        manifest = clean_partition(dataset, receipt)
        if manifest is not None:
            return dict(status="unchanged", recording_sha256=identity, run_id=receipt["run_id"], rows=manifest["rows"])
        # A previous ingestion may have stopped after archival but before clean publication.
        result = export_run(raw / "source.events", dataset / "clean", runtime)
        return dict(status="recovered", recording_sha256=identity, run_id=result["run_id"], rows=result["rows"])

    with tempfile.TemporaryDirectory(prefix="sensor-ingest-validate-") as temporary:
        snapshot = Path(temporary) / "source.events"
        snapshot.write_bytes(original)
        events, normalized_hash, duplicates = validate_recording(snapshot, runtime)
    receipt = dict(schema_version=1, recording_sha256=identity, normalized_sha256=normalized_hash,
                   run_id=events[0].run_id, source_name=source.name, duplicates_removed=duplicates)
    # Reject conflicting logical runs before archiving a new raw recording.
    clean_partition(dataset, receipt)
    raw.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ingest-", dir=raw.parent) as temporary:
        staging = Path(temporary)
        (staging / "source.events").write_bytes(original)
        (staging / "manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        staging.rename(raw)
    # Raw is published before clean becomes visible. A retry can finish interrupted conversion.
    result = materialize_run(events, normalized_hash, duplicates, dataset / "clean")
    return dict(status="imported" if result["status"] == "created" else "archived",
                recording_sha256=identity, run_id=result["run_id"], rows=result["rows"])


def ingest(source, dataset, runtime):
    """A file or a sorted, nonrecursive inbox of *.events files. One writer per dataset."""
    source = Path(source)
    sources = sorted(p for p in source.glob("*.events") if p.is_file()) if source.is_dir() else [source]
    imports = [ingest_recording(path, dataset, runtime) for path in sources]
    return dict(imports=imports, new_runs=sum(row["status"] in ("imported", "recovered") for row in imports),
                new_recordings=sum(row["status"] in ("imported", "archived") for row in imports),
                unchanged=sum(row["status"] == "unchanged" for row in imports))
