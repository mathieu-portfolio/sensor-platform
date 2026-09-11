# Truth-free global tracking and fusion

`sensor_platform_fusion` is a platform-owned C++ processor over `StreamEvent`.
It never reads entities, truth associations or evaluation files. sensor_core and
the measurement/recording/Kafka contracts are unchanged. The older core tracker
retains truth coupling and is not reused by this processor.

## Run

```sh
python scripts/dev.py build
python scripts/dev.py record build/sample.events --run-id 42
python scripts/dev.py fuse build/sample.events --output build/tracks.jsonl
python scripts/dev.py analytics tracks build/tracks.jsonl
python scripts/dev.py evaluation demo build/fusion-evaluation
python scripts/dev.py evaluation score build/fusion-evaluation/crossing/tracks.jsonl build/fusion-evaluation/crossing/truth.jsonl
```

Use global `--build-dir <existing-build>` before the command as needed. `fuse`
validates a complete recording before opening output; malformed/truncated input
leaves existing output untouched. Output paths otherwise overwrite.

`sensor_platform fuse -` consumes incremental version-1 event text from stdin,
using exactly the same processor and formatter. It accepts local `run` output or
the existing Kafka viewer's output. In a shell supporting native process pipes:

```sh
sensor_platform_kafka consumer --topic sensor-run-42 --group fresh-fusion-42 | sensor_platform fuse - --output tracks.jsonl
```

Use the built executable paths and a fresh group receiving the complete retained
run, including header/start. A viewer restarted at a committed suffix cannot
reconstruct fusion state. There is no fusion checkpoint or end-to-end offset
transaction: viewer commits precede successful downstream fusion persistence.
For recoverable processing now, record Kafka first, then fuse the complete file.
Live errors may leave a visible prefix; a missing final RUN_FINISHED snapshot means
incomplete output. File/stdin fusion are tested for byte-identical results. No
Kafka-facing behavior changed, so expensive broker integration was not rerun.

## Observation and association rules

Current `Detection.estimatedPosition` is already world Cartesian X/Y, not local
polar coordinates. `worldObservations` carries that position, acquisition time,
confidence, uncertainty and sensor/generation/scan/detection identity into a common
type. No second sensor-pose transform is applied. Units remain sandbox world units
and simulated seconds, recorded in the output's start event.

For each event, stale tracks expire before association. Each surviving track is
predicted to acquisition time with `position + velocity*dt`. Pairs within a fixed
Euclidean gate are sorted by distance, track ID, then measurement ID. Greedy
nearest pairs are accepted one-to-one **within a scan**. Unmatched measurements
create tracks in measurement order; two returns in one scan cannot merge into one
track. Later sensors can match the same track, even at the same timestamp.
Measurement IDs supply provenance/tie-breaking, never target identity.

The correction is `predicted + alpha*residual`; at positive dt, velocity receives
`beta*residual/max(dt, 0.05 seconds)`. Same-time observations correct position only.
Defaults: gate 20, alpha 0.8, beta 0.2. This is a heuristic alpha-beta filter, not
calibrated covariance. Confidence/uncertainty are retained in observations but do
not tune association/gains yet. Correlated errors and persistent false returns
can therefore create incorrect tracks.

The existing global source sequence is authoritative. Asynchronous cadences use
actual acquisition time, never wall-clock arrival time or scan count. Late times,
duplicates and gaps fail the existing validator before track mutation. There is
no reorder buffer. Identical ordered input/config in the same numeric environment
gives deterministic output; permuting simultaneous sensor events can change greedy
decisions and filter estimates.

## Lifecycle and output

- Tentative tracks confirm after two distinct acquisition times by default;
  simultaneous radar hits alone do not confirm. Both observation count and
  distinct-time count are reported.
- Confirmed tracks coast after observation age >0.5 seconds. Tentative tracks
  expire at age >=1 second; confirmed/coasting tracks at age >=2 seconds. Matching
  resumes updates. A return exactly at expiry starts a new ID.
- Empty scans and lifecycle events advance ageing. Silence has no timer event;
  expiry appears on the next input/finish. Missing scans are not fabricated.
- Sensor reset keeps global tracks and updates observation provenance. Run reset
  retires all tracks. IDs increase throughout a run, including across generations.

Options: `--gate`, `--alpha`, `--beta`, `--coast-after`, `--delete-after`,
`--tentative-timeout`, `--confirmation-times`, `--output`.

JSON Lines schema 1 emits one `GLOBAL_TRACKS` event per source event:

- run_id, run_generation, source_sequence, acquisition_time, source_type;
  RUN_STARTED also stores the filter config and coordinate/time units.
- tracks: complete active snapshot sorted by track_id, containing state,
  x/y/vx/vy at this time, last_seen, observations, distinct_times and lifetime
  contributing sensor IDs. Contributors do not claim current sensor visibility.
- associations: current scan's sensor ID/generation, scan sequence, detection ID
  and selected global track ID. No truth fields.
- retired: IDs with timeout/run_reset reason. RUN_FINISHED snapshots still-active
  tracks without incorrectly marking them lost.

Track identity is `(run_id, track_id)`. Consumers can replace their active state
from each snapshot. There is no backward smoothing or revision of past output.

## Evaluation and limitations

`evaluation/` generates analytic trajectories and seeded observations in
`measurements.events`; `truth.jsonl` is separate. Only measurements reach C++
fusion. These fixtures test association/lifecycle, not radar fidelity or core
sensor physics. The normal simulator's recording also works with the same CLI.

Evaluation takes the final snapshot after all sensors at each acquisition time.
Confirmed/coasting tracks match truth one-to-one by nearest distance within an
independent 5-unit gate. Tentative tracks are separate and do not satisfy recall.
RMSE covers matched positions only. Missed targets/false tracks are sample counts;
unique false-track count is also reported. An ID switch means a target matched a
different ID than its previous match, including across a gap; run generations
separate that history. This small evaluator also has crossing ambiguities and is
not a standard MOT benchmark implementation.

Actual seed-42 results, Windows/MSVC Debug, default fusion settings:

| Fixture | Target samples | Position RMSE | Missed samples | False-track samples | ID switches |
| --- | ---: | ---: | ---: | ---: | ---: |
| Two overlapping 4 Hz sensors | 33 | 0.0060 | 1 | 0 | 0 |
| Three sensors at 2/4/8 Hz | 65 | 0.0080 | 1 | 0 | 0 |
| Outage, noise/dropouts, persistent false return | 65 | 0.7364 | 1 | 20 | 0 |
| Sparse close crossing | 10 | 0.0372 | 2 | 0 | 2 |

Initial misses are confirmation delay. Sensor 2's outage spans [2,5); noise has
0.7-unit standard deviation and drop probability 0.15. Other sensors maintain the
target, while one persistent false return confirms, coasts, then expires. Crossing
targets pass between sparse samples: nearest neighbour swaps their identities
while maintaining low position error. Good position accuracy alone does not mean
correct tracking. Separate equal-distance tests exercise deterministic ties.

## Analytics and validation

`analytics tracks` validates completed output and exposes DuckDB `track_samples`,
keeping the final snapshot per timestamp to avoid inflating statistics with
overlapping scans/finish events. `analytics/sql/fusion/summary.sql` reports track
lifetime samples, tentative/coasting counts, observations, contributor count and
maximum observation age. This path never loads truth. Normal measurement Parquet
schemas stay unchanged; fused Parquet is deferred until there is a concrete need.

```sh
python scripts/dev.py test fusion
python scripts/dev.py test evaluation
python scripts/dev.py test analytics -k TrackAnalytics
```

Tests cover world coordinates, overlapping/asynchronous sensors, one-to-one ties,
gates, ageing, sensor/world resets, invalid input, deterministic file/stream
equivalence, all four fixtures and evaluation metric definitions.

Next: compare association/gain settings across multiple seeds and sampling gaps,
measuring identity continuity alongside position error. Use the results to justify
the next motion-model/association improvement while retaining this baseline.
