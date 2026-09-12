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
