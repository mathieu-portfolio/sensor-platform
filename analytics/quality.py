"""Source-derived counts and reconciliation of the actual clean files."""
import duckdb

CHECKS = ["run_lifecycle", "global_sequence", "sensor_scan_sequence",
          "acquisition_time", "logical_event_identity", "measurement_count"]


def source_counts(events):
    scans = [event for event in events if event.kind == "MEASUREMENTS"]
    return dict(events=len(events), scans=len(scans),
                measurements=sum(len(event.detections) for event in scans))


def reconcile(partition, expected):
    """Read persisted Parquet, independently of the row-conversion buffers."""
    with duckdb.connect() as connection:
        actual = {}
        for table in ("events", "scans", "measurements"):
            connection.read_parquet(str(partition / f"{table}.parquet"),
                                    hive_partitioning=False).create_view(table)
            actual[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        if actual != expected:
            raise ValueError(f"clean reconciliation failed: expected {expected}, actual {actual}")
        # Check every scan, including empty scans, rather than only aggregate totals.
        mismatch = connection.execute("""
            SELECT count(*) FROM (
                SELECT stream_sequence, measurement_count FROM events WHERE event_type='MEASUREMENTS'
                EXCEPT SELECT stream_sequence, measurement_count FROM scans
            )
        """).fetchone()[0]
        mismatch += connection.execute("""
            SELECT count(*) FROM scans s FULL OUTER JOIN
                (SELECT stream_sequence, count(*) n FROM measurements GROUP BY stream_sequence) m
                USING (stream_sequence)
            WHERE s.stream_sequence IS NULL OR s.measurement_count != coalesce(m.n, 0)
        """).fetchone()[0]
        if mismatch:
            raise ValueError(f"clean reconciliation failed: {mismatch} inconsistent scan measurement counts")
    return actual
