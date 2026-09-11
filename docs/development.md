# Developer commands

`python scripts/dev.py` is a stdlib router for existing commands, not another build
system. Commands run from sensor-platform; all relative paths refer to this repo,
even when the script is invoked elsewhere. Global options precede the command:
`--build-dir build`, `--config Debug`, `--python <interpreter>`, `--dry-run`.
The script selects `.venv` for Python tooling when present, otherwise the current
interpreter. It handles Visual Studio versus single-config binary paths and the
Windows Path/PATH environment collision. It never installs dependencies or starts
a broker. Command traces go to stderr so stdout remains usable as event/CSV output.

```sh
python scripts/dev.py build
python scripts/dev.py test unit
python scripts/dev.py test unit -R events
python scripts/dev.py test platform -N
python scripts/dev.py run
python scripts/dev.py record build/sample.events --run-id 42
python scripts/dev.py replay build/sample.events
python scripts/dev.py analytics export build/sample.events data
python scripts/dev.py analytics query data --sql analytics/sql/sensor_summary.sql
python scripts/dev.py experiments run experiments/configs/baseline.json build/experiments/baseline
python scripts/dev.py experiments report build/experiments
```

Build configures only a new directory unless `--configure` or CMake arguments are
supplied. Existing caches/toolchains are reused; CMake handles normal regeneration.
Use `build --target sensor_platform` for a focused target, or
`build --configure -- -DSENSOR_PLATFORM_KAFKA=ON` for configure options. Changing
`--config` in a single-config build also requires `build --configure`.
Tests never build implicitly. Analytics export and experiment run receive the
selected runtime/binary directory unless you supply their existing override flags.
Other arguments are forwarded unchanged; for leading flags use e.g.
`run -- --run-id 42`. Direct CMake and underlying CLI commands remain supported.

## Focused test selection

| `test` group | Existing tests selected | Additional targeting |
| --- | --- | --- |
| `unit` (default) | Two C++ runner/event CTest executables | `-R events` or `-R multi_sensor` |
| `platform` | All three platform CTest tests | `-N` lists without execution |
| `integration` | Local CLI recording/output CTest only | No broker required |
| `analytics` | Python Parquet/DuckDB unittest suite | `-k fields` |
| `experiments` | Python metric/config/runtime unittest suite | `-k MetricTests` |
| `workflow` | Developer CLI unittest suite | `-k filters` |
| `kafka` | Existing `tools/validate_kafka.py` | Explicit opt-in; running broker required |

CTest labels are `unit`, `platform`, `integration`; the Python and Kafka groups
route to their existing runners, without duplicate CTest registration or a Python
dependency in C++ configuration. A CTest filter matching no tests fails clearly.
Python unittest uses its normal `-k` behavior (zero matches are reported, not failed).
For example:

```sh
python scripts/dev.py --build-dir build/consumer-verified test experiments -k MetricTests
python scripts/dev.py --build-dir build/consumer-verified test analytics -k actual_three
python scripts/dev.py --build-dir build/kafka-verified test kafka --kafka-home build/dependency-inspection/kafka_2.13-4.0.0 --java java
python scripts/dev.py --build-dir build/kafka-verified kafka producer --topic sensor-run-42 --run-id 42
```

The last two commands are examples for an existing Kafka-enabled build and broker;
use your actual installation paths. [Kafka development](kafka.md) owns setup and
topic instructions. Runtime/data details remain in [recording](event-recording.md),
[analytics](analytics.md) and [experiments](experiments.md).

For platform-only changes, start with affected groups. Use the sibling's own build
only when the core/app boundary is affected. Sandbox CTest already discovers
individual GoogleTests: `ctest --test-dir <sandbox-build> -N`, then `-R <suite/name>`.
Keep its build separate; platform configuration intentionally disables sandbox
app/tests. No full Kafka/app regression is needed for a docs or command-routing edit.
