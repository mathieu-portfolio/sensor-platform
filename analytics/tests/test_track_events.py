import json
from pathlib import Path
import tempfile
import unittest

from analytics.track_events import open_tracks, load_frames


class TrackAnalyticsTests(unittest.TestCase):
    def test_empty_output_and_last_snapshot_per_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "tracks.jsonl"
            frames = [dict(schema_version=1, event_type="GLOBAL_TRACKS", run_id=2**64-1, run_generation=0,
                           source_sequence=i, source_type=kind, acquisition_time=0, tracks=[])
                      for i, kind in enumerate(["RUN_STARTED", "MEASUREMENTS", "RUN_FINISHED"], 1)]
            source.write_text("\n".join(map(json.dumps, frames)))
            with open_tracks(source) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM track_samples").fetchone()[0], 0)
            track = dict(track_id=1, state="confirmed", x=4, y=3, vx=0, vy=0,
                         last_seen=0, observations=1, sensors=[1])
            frames[1]["tracks"] = [track]
            frames[2]["tracks"] = [track | dict(observations=2, sensors=[1, 2])]
            source.write_text("\n".join(map(json.dumps, frames)))
            with open_tracks(source) as db:
                row = db.execute("SELECT run_id, source_sequence, observations, sensor_count FROM track_samples").fetchone()
                self.assertEqual(row, (2**64-1, 3, 2, 2))
                sql = Path(__file__).resolve().parents[1] / "sql/fusion/summary.sql"
                self.assertEqual(db.execute(sql.read_text()).fetchone()[5], 1)
            frames[1]["source_sequence"] = 1
            source.write_text("\n".join(map(json.dumps, frames)))
            with self.assertRaisesRegex(ValueError, "order"):
                load_frames(source)
