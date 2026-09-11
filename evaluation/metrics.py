"""Truth joins exist only here, after fusion has finished."""
import math
from analytics.track_events import load_frames


def evaluate(frames, truth, gate=5):
    if not math.isfinite(gate) or gate <= 0:
        raise ValueError("evaluation gate must be finite and positive")
    index = {(f["run_id"], f["run_generation"], f["source_sequence"]): f for f in frames}
    errors, missed, false, switches, truth_samples, tentative = [], 0, 0, 0, 0, 0
    previous, false_ids, seen_frames = {}, set(), set()
    for row in truth:
        key = (row["run_id"], row["run_generation"], row["source_sequence"])
        if key in seen_frames:
            raise ValueError("duplicate truth snapshot")
        seen_frames.add(key)
        frame = index[key]
        if frame["acquisition_time"] != row["acquisition_time"]:
            raise ValueError("truth/fusion acquisition timestamp mismatch")
        targets = row["entities"]
        if len({t["truth_id"] for t in targets}) != len(targets):
            raise ValueError("duplicate truth target")
        tracks = [t for t in frame["tracks"] if t["state"] != "tentative"]
        tentative += len(frame["tracks"]) - len(tracks)
        truth_samples += len(targets)
        candidates = []
        for i, target in enumerate(targets):
            for j, track in enumerate(tracks):
                distance = math.hypot(target["x"] - track["x"], target["y"] - track["y"])
                if distance <= gate:
                    candidates.append((distance, target["truth_id"], track["track_id"], i, j))
        used_truth, used_tracks = set(), set()
        for distance, identity, track_id, i, j in sorted(candidates):
            if i in used_truth or j in used_tracks:
                continue
            used_truth.add(i); used_tracks.add(j)
            errors.append(distance)
            truth_key = (row["run_id"], row["run_generation"], identity)
            switches += truth_key in previous and previous[truth_key] != track_id
            previous[truth_key] = track_id
        missed += len(targets) - len(used_truth)
        false += len(tracks) - len(used_tracks)
        false_ids.update((row["run_id"], t["track_id"]) for j, t in enumerate(tracks) if j not in used_tracks)
    return dict(evaluated_frames=len(truth), target_samples=truth_samples, matched_samples=len(errors),
                position_rmse=math.sqrt(sum(e*e for e in errors)/len(errors)) if errors else None,
                mean_position_error=sum(errors)/len(errors) if errors else None,
                missed_target_samples=missed, false_track_samples=false, unique_false_tracks=len(false_ids),
                id_switches=switches, tentative_track_samples=tentative, evaluation_gate=gate)
