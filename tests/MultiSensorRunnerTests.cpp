#include "MultiSensorRunner.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <map>
#include <stdexcept>
#include <string>

using namespace sensor_sandbox;
using namespace sensor_platform;

namespace {
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

void sameScan(const SensorScan& a, const SensorScan& b) {
    check(a.sensorId == b.sensorId && a.sequence == b.sequence &&
          a.simulationTimeSeconds == b.simulationTimeSeconds, "scan identity/time differs");
    check(a.detections.size() == b.detections.size(), "measurement count differs");
    for (std::size_t i = 0; i < a.detections.size(); ++i) {
        const auto& x = a.detections[i];
        const auto& y = b.detections[i];
        check(x.id == y.id && x.sensorId == y.sensorId &&
              x.estimatedPosition.x == y.estimatedPosition.x &&
              x.estimatedPosition.y == y.estimatedPosition.y &&
              x.confidence == y.confidence && x.uncertaintyRadius == y.uncertaintyRadius,
              "measurement differs");
    }
}

std::vector<Entity> entities() {
    Entity entity;
    entity.id = 10;
    entity.position = {100, 0};
    entity.velocity = {10, 0};
    return {entity};
}

std::vector<SensorConfig> configs(bool noisy = false) {
    std::vector<SensorConfig> result{
        {.id = 1, .position = {0, 0}, .definition = {.range = 200, .refreshRateHz = 1}, .seed = 42},
        {.id = 2, .position = {50, 20}, .definition = {.range = 150, .refreshRateHz = 2}, .seed = 73},
        {.id = 3, .position = {150, -20}, .definition = {.range = 100, .refreshRateHz = 4}, .seed = 99}
    };
    if (noisy) {
        for (auto& config : result) {
            config.definition.rangeNoise = 7;
            config.definition.detectionProbability = 0.5f;
            config.definition.falsePositiveRateHz = 4;
        }
    }
    return result;
}

using Streams = std::map<SensorId, std::vector<SensorScan>>;
Streams run(const std::vector<SensorConfig>& configuration) {
    MultiSensorRunner runner(entities(), configuration);
    Streams streams;
    for (int tick = 0; tick <= 20; ++tick) {
        for (const auto& scan : runner.advanceTo(tick * 0.25f)) streams[scan.sensorId].push_back(scan);
        check(runner.world().entities()[0].position.x == 100 + tick * 2.5f, "world advanced more than once");
    }
    return streams;
}

void sameStream(const std::vector<SensorScan>& a, const std::vector<SensorScan>& b) {
    check(a.size() == b.size(), "stream size differs");
    for (std::size_t i = 0; i < a.size(); ++i) sameScan(a[i], b[i]);
}

void cadenceAndSharedWorld() {
    const auto streams = run(configs());
    for (const auto& [id, scans] : streams) {
        const float rate = id == 1 ? 1.0f : id == 2 ? 2.0f : 4.0f;
        check(scans.size() == static_cast<std::size_t>(5 * rate + 1), "wrong cadence");
        for (std::size_t i = 0; i < scans.size(); ++i) {
            const auto& scan = scans[i];
            check(scan.sequence == i + 1 && scan.simulationTimeSeconds == i / rate, "wrong deadline/sequence");
            check(scan.detections.size() == 1, "expected one observed entity");
            check(scan.detections[0].estimatedPosition.x == 100 + 10 * scan.simulationTimeSeconds,
                  "sensors did not observe the same world trajectory");
        }
    }
    auto configuration = configs();
    configuration[0].definition.range = 1;
    MultiSensorRunner emptyCoverage(entities(), configuration);
    const auto scans = emptyCoverage.advanceTo(0);
    check(scans.size() == 3 && scans[0].detections.empty() && scans[1].detections.size() == 1,
          "coverage configuration or empty completed scan lost");
}

void determinismAndOrdering() {
    auto configuration = configs(true);
    const auto first = run(configuration);
    const auto repeated = run(configuration);
    std::reverse(configuration.begin(), configuration.end());
    const auto reversed = run(configuration);
    configuration.erase(configuration.begin()); // Remove C; A/B must be unaffected.
    const auto subset = run(configuration);
    for (const auto& [id, stream] : first) {
        sameStream(stream, repeated.at(id));
        sameStream(stream, reversed.at(id));
        if (id != 3) sameStream(stream, subset.at(id));
    }
}

void independentReset() {
    MultiSensorRunner runner(entities(), configs(true)), control(entities(), configs(true));
    runner.advanceTo(0);
    control.advanceTo(0);
    runner.advanceTo(0.25f);
    control.advanceTo(0.25f);
    runner.resetSensor(1);
    const auto restarted = runner.advanceTo(0.25f);
    check(restarted.size() == 1 && restarted[0].sensorId == 1 && restarted[0].sequence == 1 &&
          restarted[0].simulationTimeSeconds == 0.25f, "reset must restart only A at current time");
    check(runner.world().entities()[0].position.x == 102.5f, "reset moved world");
    for (int tick = 2; tick <= 12; ++tick) {
        const auto actual = runner.advanceTo(tick * 0.25f);
        const auto expected = control.advanceTo(tick * 0.25f);
        for (SensorId id : {2, 3}) {
            const auto a = std::find_if(actual.begin(), actual.end(), [=](const auto& s) { return s.sensorId == id; });
            const auto b = std::find_if(expected.begin(), expected.end(), [=](const auto& s) { return s.sensorId == id; });
            check((a == actual.end()) == (b == expected.end()), "reset changed another deadline");
            if (a != actual.end()) sameScan(*a, *b);
        }
    }
}

template<class F> void rejects(F action) {
    try { action(); } catch (const std::invalid_argument&) { return; }
    throw std::runtime_error("expected invalid_argument");
}

void invalidInputs() {
    auto configuration = configs();
    configuration.push_back(configuration.front());
    rejects([&] { MultiSensorRunner runner(entities(), configuration); });
    configuration = configs();
    for (float rate : {0.0f, -1.0f, std::numeric_limits<float>::infinity(),
                       std::numeric_limits<float>::quiet_NaN()}) {
        configuration[0].definition.refreshRateHz = rate;
        rejects([&] { MultiSensorRunner runner(entities(), configuration); });
    }
    MultiSensorRunner runner(entities(), configs());
    runner.advanceTo(0.5f);
    for (float time : {-1.0f, 0.25f, std::numeric_limits<float>::infinity(),
                       std::numeric_limits<float>::quiet_NaN()}) {
        rejects([&] { runner.advanceTo(time); });
    }
    rejects([&] { runner.resetSensor(999); });
    check(runner.world().entities()[0].position.x == 105, "invalid time mutated world");
    check(runner.advanceTo(0.5f).empty(), "invalid input mutated schedules");
}
} // namespace

int main() {
    try {
        cadenceAndSharedWorld();
        determinismAndOrdering();
        independentReset();
        invalidInputs();
        std::cout << "Multi-sensor runner tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
