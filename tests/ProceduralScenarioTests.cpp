#include "ProceduralScenario.hpp"
#include "EventRecording.hpp"
#include "viewer/ViewerState.hpp"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>

using namespace sensor_platform;
using namespace sensor_sandbox;
namespace {
void check(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
template<class F> void rejects(F operation) {
    try { operation(); } catch (const std::invalid_argument&) { return; }
    throw std::runtime_error("Expected invalid configuration to be rejected");
}
std::string layout(const GeneratedScenario& scenario) {
    std::ostringstream output;
    writeScenarioLayout(output, scenario);
    return output.str();
}
std::string recording(const GeneratedScenario& scenario) {
    std::ostringstream output;
    IncrementalRecording writer(output);
    runProcedural(43, scenario, [&](const auto& event) { writer.append(event); });
    writer.finish();
    return output.str();
}
void determinismAndSeedIsolation() {
    ProceduralConfig config;
    const auto first = generateScenario(config);
    const auto bytes = recording(first);
    check(bytes == recording(generateScenario(config)), "same configuration changed recording");
    ++config.scenarioSeed;
    const auto changedTargets = generateScenario(config);
    check(layout(first) == layout(changedTargets), "target seed changed layout");
    check(bytes != recording(changedTargets), "target seed did not change recording");
    check(first.entities[0].position.x != changedTargets.entities[0].position.x, "target seed did not change targets");
    for (std::size_t i = 0; i < first.sensors.size(); ++i) {
        const auto& a = first.sensors[i];
        const auto& b = changedTargets.sensors[i];
        check(a.seed == b.seed && a.definition.rangeNoise == b.definition.rangeNoise &&
              a.definition.refreshRateHz == b.definition.refreshRateHz &&
              a.definition.detectionProbability == b.definition.detectionProbability &&
              a.definition.falsePositiveRateHz == b.definition.falsePositiveRateHz, "target seed changed sensor quality");
    }
    config = {};
    ++config.layoutSeed;
    const auto changedLayout = generateScenario(config);
    check(layout(first) != layout(changedLayout), "layout seed did not change layout");
    check(bytes != recording(changedLayout), "layout seed did not change recording");
    MultiSensorRunner a(first.entities, first.sensors), b(changedLayout.entities, changedLayout.sensors);
    for (int tick = 0; tick <= 160; ++tick) {
        a.advanceTo(tick / 8.0f);
        b.advanceTo(tick / 8.0f);
        for (std::size_t i = 0; i < first.entities.size(); ++i) {
            const auto& x = a.world().entities()[i];
            const auto& y = b.world().entities()[i];
            check(x.position.x == y.position.x && x.position.y == y.position.y &&
                  x.velocity.x == y.velocity.x && x.velocity.y == y.velocity.y, "layout seed changed trajectory");
        }
    }
}
void coverageAndInteraction() {
    // Exercise independent seed pairs, count limits and duration scaling. Every
    // target must be jointly observable throughout the first half of each run.
    for (std::uint32_t seed = 0; seed < 24; ++seed) {
        ProceduralConfig config{seed, seed * 31 + 7, seed % 2 ? 4 : 120,
            seed % 3 ? 4 : 12, seed % 3 ? 3 : 8};
        const auto generated = generateScenario(config);
        std::set<ScenarioPathMotion> motions;
        std::set<float> rates;
        for (const auto& entity : generated.entities) motions.insert(entity.scenarioMotion);
        for (const auto& sensor : generated.sensors) {
            rates.insert(sensor.definition.refreshRateHz);
            check(sensor.definition.range - std::hypot(sensor.position.x, sensor.position.y) >= 169.99f,
                  "sensor does not cover common observation disk");
        }
        check(motions.size() == 4 && rates.size() == 3, "balanced motion/cadence diversity lost");
        MultiSensorRunner runner(generated.entities, generated.sensors);
        for (int tick = 0; tick <= config.durationSeconds * 8; ++tick) {
            const float time = tick / 8.0f;
            runner.advanceTo(time);
            for (const auto& entity : runner.world().entities()) {
                check(std::isfinite(entity.position.x) && std::isfinite(entity.velocity.y) &&
                      std::hypot(entity.position.x, entity.position.y) < 300, "unbounded generated trajectory");
                if (time <= config.durationSeconds * 0.5f)
                    for (const auto& sensor : generated.sensors)
                        check(std::hypot(entity.position.x - sensor.position.x, entity.position.y - sensor.position.y)
                              <= sensor.definition.range, "target not jointly observable in first half");
                if (time == config.durationSeconds * 0.5f)
                    check(std::hypot(entity.position.x, entity.position.y) < 60, "targets did not converge through common area");
            }
        }
    }
}
void motionAndViewer() {
    const auto scenario = generateScenario({});
    MultiSensorRunner runner(scenario.entities, scenario.sensors);
    runner.advanceTo(10);
    for (std::size_t i = 0; i < scenario.entities.size(); ++i) {
        const auto& start = scenario.entities[i];
        const auto& later = runner.world().entities()[i];
        check(std::hypot(start.position.x - later.position.x, start.position.y - later.position.y) > 100,
              "target did not move");
        if (start.scenarioMotion == ScenarioPathMotion::Linear)
            check(std::abs(later.position.x - start.position.x - 10 * start.velocity.x) < 0.001f,
                  "straight motion did not retain velocity");
    }
    // Absolute-time procedural trajectories must not depend on polling history.
    MultiSensorRunner fine(scenario.entities, scenario.sensors);
    for (int i = 0; i <= 80; ++i) fine.advanceTo(i / 8.0f);
    for (std::size_t i = 0; i < scenario.entities.size(); ++i)
        check(fine.world().entities()[i].position.x == runner.world().entities()[i].position.x &&
              fine.world().entities()[i].position.y == runner.world().entities()[i].position.y,
              "motion depends on polling history");
    // Behavioral checks: turns bend, zigzags reverse lateral velocity, bursts
    // increase forward speed, while straight paths keep their initial velocity.
    std::vector<float> minimum(scenario.entities.size(), 1e6f), maximum(scenario.entities.size(), -1e6f);
    MultiSensorRunner motion(scenario.entities, scenario.sensors);
    for (int tick = 0; tick <= 160; ++tick) {
        motion.advanceTo(tick / 8.0f);
        for (std::size_t i = 0; i < scenario.entities.size(); ++i) {
            const auto& entity = motion.world().entities()[i];
            const float lateral = entity.scenarioDirection.x * entity.velocity.y - entity.scenarioDirection.y * entity.velocity.x;
            minimum[i] = std::min(minimum[i], lateral);
            maximum[i] = std::max(maximum[i], lateral);
            if (entity.scenarioMotion == ScenarioPathMotion::Linear)
                check(entity.velocity.x == scenario.entities[i].velocity.x && entity.velocity.y == scenario.entities[i].velocity.y,
                      "straight motion maneuvered");
        }
    }
    for (std::size_t i = 0; i < scenario.entities.size(); ++i) {
        const auto& entity = motion.world().entities()[i];
        if (entity.scenarioMotion == ScenarioPathMotion::Arc || entity.scenarioMotion == ScenarioPathMotion::ZigZag)
            check(minimum[i] < -0.1f && maximum[i] > 0.1f, "curved/zigzag path did not turn");
        if (entity.scenarioMotion == ScenarioPathMotion::AccelerationBurst)
            check(std::hypot(entity.velocity.x, entity.velocity.y) > 1.29f * entity.scenarioSpeed,
                  "maneuver burst did not accelerate");
    }
    std::istringstream geometry(layout(scenario));
    const auto sensors = viewer::readLayout(geometry);
    check(sensors.size() == scenario.sensors.size(), "viewer layout count mismatch");
    for (std::size_t i = 0; i < sensors.size(); ++i)
        check(sensors[i].id == scenario.sensors[i].id &&
              std::abs(sensors[i].x - scenario.sensors[i].position.x) < 0.00001 &&
              std::abs(sensors[i].range - scenario.sensors[i].definition.range) < 0.00001,
              "viewer geometry differs from simulated network");
    std::istringstream events(recording(scenario));
    viewer::Playback playback(readRecording(events));
    playback.advance(20);
    check(playback.done() && playback.state().sensors.size() == 3, "viewer rejected procedural recording");
}
void configValidation() {
    std::istringstream input("SENSOR_PROCEDURAL 1\n2026 73 20 4 3\n");
    const auto config = readProceduralConfig(input);
    check(recording(generateScenario(config)) == recording(generateScenario({})), "file/default configuration mismatch");
    for (const auto* text : {"SENSOR_PROCEDURAL 2\n1 2 20 4 3", "SENSOR_PROCEDURAL 1\n-1 2 20 4 3",
        "SENSOR_PROCEDURAL 1\n4294967296 2 20 4 3", "SENSOR_PROCEDURAL 1\n1 2 0 4 3",
        "SENSOR_PROCEDURAL 1\n1 2 20 0 3", "SENSOR_PROCEDURAL 1\n1 2 20 4 9",
        "SENSOR_PROCEDURAL 1\n1 2 20 4", "SENSOR_PROCEDURAL 1\n1 2 20 4 3 extra"})
        rejects([&] { std::istringstream bad(text); readProceduralConfig(bad); });
    rejects([] { generateScenario({0, 0, 121, 4, 3}); });
    const auto minimal = generateScenario({0xffffffffU, 0xffffffffU, 4, 1, 1});
    check(minimal.entities.size() == 1 && minimal.sensors.size() == 1, "minimum count/maximum seed rejected");
}

float radius(const Entity& entity) { return std::hypot(entity.position.x, entity.position.y); }
void parameterEffects() {
    const auto defaults = generateScenario({});
    ProceduralConfig config;
    config.speedMin = config.speedMax = 1;
    const auto slow = generateScenario(config);
    config.speedMin = config.speedMax = 30;
    const auto fast = generateScenario(config);
    check(fast.entities[0].scenarioSpeed > slow.entities[0].scenarioSpeed * 20, "speed range has no material effect");
    config = {};
    config.maneuver = 0;
    const auto calm = generateScenario(config);
    config.maneuver = 3;
    const auto agile = generateScenario(config);
    for (std::size_t i = 0; i < calm.entities.size(); ++i) {
        const auto& a = calm.entities[i];
        const auto& b = agile.entities[i];
        check(a.scenarioLateralAmplitude == 0 && a.scenarioBurstMultiplier == 1, "calm paths still maneuver");
        if (b.scenarioMotion == ScenarioPathMotion::Arc || b.scenarioMotion == ScenarioPathMotion::ZigZag)
            check(std::abs(b.scenarioLateralAmplitude) >= 36, "maneuver intensity did not increase turns");
        if (b.scenarioMotion == ScenarioPathMotion::AccelerationBurst)
            check(b.scenarioBurstMultiplier >= 1.9f, "maneuver intensity did not increase bursts");
    }
    config = {};
    config.convergence = 0;
    const auto dispersed = generateScenario(config);
    MultiSensorRunner inward(defaults.entities, defaults.sensors), outward(dispersed.entities, dispersed.sensors);
    inward.advanceTo(10); outward.advanceTo(10);
    for (std::size_t i = 0; i < defaults.entities.size(); ++i)
        check(radius(outward.world().entities()[i]) > radius(inward.world().entities()[i]) + 100,
              "dispersed targets still converge");
    config = {};
    config.spawnSpread = .4f;
    const auto near = generateScenario(config);
    config.spawnSpread = 1.5f;
    const auto far = generateScenario(config);
    check(radius(far.entities[0]) > radius(near.entities[0])*3, "spawn spread did not move starts");
    config = {};
    config.layoutSpread = .25f;
    const auto compact = generateScenario(config);
    config.layoutSpread = 3;
    const auto wide = generateScenario(config);
    check(std::hypot(wide.sensors[0].position.x, wide.sensors[0].position.y) >
          std::hypot(compact.sensors[0].position.x, compact.sensors[0].position.y)*10, "layout spread ineffective");
    config = {};
    config.coverage = .65f;
    const auto small = generateScenario(config);
    config.coverage = 1.6f;
    const auto large = generateScenario(config);
    check(large.sensors[0].definition.range > small.sensors[0].definition.range*1.5f, "coverage scale ineffective");
    config = {};
    config.noise = 0; config.clutter = 0;
    const auto clean = generateScenario(config);
    config.noise = 5; config.clutter = 12; config.reliability = .35f;
    const auto noisy = generateScenario(config);
    for (std::size_t i = 0; i < clean.sensors.size(); ++i) {
        const auto& a = clean.sensors[i].definition;
        const auto& b = noisy.sensors[i].definition;
        check(a.rangeNoise == 0 && b.rangeNoise >= 1.5f, "noise scale ineffective");
        check(a.falsePositiveRateHz == 0 && b.falsePositiveRateHz >= .6f, "clutter scale ineffective");
        check(b.detectionProbability < a.detectionProbability*.36f, "reliability scale ineffective");
    }
    // Every knob individually reaches the recording path, repeats exactly, and
    // rejects non-finite/out-of-range input rather than silently clamping it.
    for (const auto& parameter : proceduralParameters) {
        ProceduralConfig low, high;
        low.durationSeconds = high.durationSeconds = 4;
        low.speedMin = high.speedMin = 1;
        low.speedMax = high.speedMax = 30;
        low.*(parameter.member) = parameter.minimum;
        high.*(parameter.member) = parameter.maximum;
        const auto lowBytes = recording(generateScenario(low));
        const auto highBytes = recording(generateScenario(high));
        check(lowBytes != highBytes, "parameter did not affect recorded measurements");
        check(highBytes == recording(generateScenario(high)), "complete configuration is not deterministic");
        high.*(parameter.member) = parameter.maximum + 1;
        rejects([&] { generateScenario(high); });
        high.*(parameter.member) = std::numeric_limits<float>::quiet_NaN();
        rejects([&] { generateScenario(high); });
    }
    config = {}; config.speedMin = 20; config.speedMax = 10;
    rejects([&] { generateScenario(config); });
}

void variedCoverageAndSeeds() {
    for (unsigned seed = 0; seed < 24; ++seed) {
        ProceduralConfig config{seed, seed*31+7, seed%2 ? 4 : 120, seed%3 ? 4 : 12, seed%3 ? 1 : 8};
        unsigned random = seed + 1;
        for (const auto& parameter : proceduralParameters) {
            random = random*1664525U + 1013904223U;
            const float fraction = seed < 2 ? static_cast<float>(seed) : (random%1001)/1000.0f;
            config.*(parameter.member) = parameter.minimum + (parameter.maximum-parameter.minimum)*fraction;
        }
        if (config.speedMin > config.speedMax) std::swap(config.speedMin, config.speedMax);
        const auto scenario = generateScenario(config);
        auto otherSeed = config; ++otherSeed.scenarioSeed;
        check(layout(scenario) == layout(generateScenario(otherSeed)), "target seed changed extended layout");
        otherSeed = config; ++otherSeed.layoutSeed;
        const auto other = generateScenario(otherSeed);
        MultiSensorRunner a(scenario.entities, scenario.sensors), b(other.entities, other.sensors);
        for (int step = 0; step <= 16; ++step) {
            const float time = config.durationSeconds * step / 16.0f;
            a.advanceTo(time); b.advanceTo(time);
            for (std::size_t i = 0; i < scenario.entities.size(); ++i) {
                const auto& entity = a.world().entities()[i];
                check(std::isfinite(radius(entity)) && radius(entity) < 1500, "extended path is unbounded");
                check(entity.position.x == b.world().entities()[i].position.x &&
                      entity.position.y == b.world().entities()[i].position.y, "layout seed changed extended motion");
                if (step <= 8) for (const auto& sensor : scenario.sensors)
                    check(std::hypot(entity.position.x-sensor.position.x, entity.position.y-sensor.position.y)
                          <= sensor.definition.range, "extended path escaped guaranteed first-half coverage");
            }
        }
    }
}
}
int main() {
    try {
        determinismAndSeedIsolation();
        coverageAndInteraction();
        motionAndViewer();
        configValidation();
        parameterEffects();
        variedCoverageAndSeeds();
        std::cout << "Procedural generation, motion, recording and viewer checks passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
