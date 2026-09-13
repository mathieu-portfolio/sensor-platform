# Presentation assets

`platform-viewer.png` is the unedited screenshot from the verified Windows/raylib
5.5 viewer launch on 2026-09-12 (1800 x 1200 framebuffer with high-DPI scaling).
It was copied from the existing local `build/viewer-verified.png` artifact; no
new run or synthetic image was created for the README.

The source was the default three-radar run-42 recording, with
[`sample.sensors.layout`](../sample.sensors.layout). The final frame shows 15
events, 10 scans, 11 measurements and 2 active tracks. Circles are supplied sensor
coverage, crosses are latest-scan measurements and squares are fused tracks.
Ground truth is not loaded. This is the same sample used by the
[curated demo](../demo.md), not a load-experiment visualization.

The original launch used `--frames 360 --screenshot build/viewer-verified.png`.
For a current build, follow [viewer setup](../viewer.md) and use the prepared
recording/layout command in `demo/results/viewer.md`. The executable and runtime
libraries must already be available. Full recordings, datasets, build products
and generated reports stay out of Git; only this presentation screenshot is retained.

## Curated study results

`curated-study.png` is the unedited 1440 x 960 raylib application capture from 2026-09-13, copied from `build/curated-study-overview.png`. It shows the completed 300-run study, 20 paired target seeds per condition, five condition-mean charts and sample-SD whiskers.

Capture command: `python scripts/dev.py results --frames 3 --screenshot build/curated-study-overview.png`. The application loaded only `data/studies/curated/analysis/results.view`; it did not run simulation. The overview, reliability and convergence detail screenshots were visually inspected.

Study identity: `a3777b933edb2dd0c9a65db8dc294a513a69ea46459641b0c0c67f5470ddb752`.

Display-export SHA-256: `080d8c4e7813cc3b72e3422a5723cd4a1bc863608a08d44f6ce78458d46bc003`.

Screenshot SHA-256: `6361b0187196ab2bea738d743f9c3fda4de213fbc33337a6c468611489281bd1`.

The study definition, reproduction commands, actual findings and timing are documented in [the curated study](../curated-study.md). Generated recordings and datasets remain outside Git.
