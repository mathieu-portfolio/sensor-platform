# Operational guidance

- `sensor-platform` and `../sensor-sandbox` are separate Git repositories. Keep
  changes and commits scoped to their owning repository; do not copy/vendor or
  merge the sibling checkout. Extracting a third core repository is deferred.
- Link the sibling's `sensor_core` CMake target. Core consumers must stay free of
  raylib, sandbox presentation and app orchestration. Transport, persistence,
  analytics and experiment tooling belong in this repository.
- Normal runtime events/datasets contain no evaluation truth IDs or associations.
  Keep evaluation-only truth separate from measurement contracts and consumers.
- Use `python scripts/dev.py --help` for common commands. It wraps existing CMake,
  CTest, runtime and Python CLIs; detailed behavior lives in `docs/`.
- Reuse an appropriate existing build directory with `--build-dir`; configuration
  defaults to Debug. Build explicitly before tests; tests never silently rebuild.
  Python data tooling uses `.venv` when available. No dependency installation or
  broker startup is implicit.
- Prefer affected test groups/name filters. Kafka validation is opt-in and needs
  a running broker. Do not repeat full sandbox/app/Kafka suites for documentation
  or isolated platform/tooling changes; broaden only for affected boundaries or failures.
- Inspect diffs/status in both repositories, preserve unrelated work, and commit
  only requested changes. Do not commit generated builds, recordings or datasets.
