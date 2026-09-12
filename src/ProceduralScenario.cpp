#include "ProceduralScenario.hpp"
#include "RunSession.hpp"
#include "sensor/scenarios/ProceduralSpawnSystem.hpp"

#include <algorithm>
#include <charconv>
#include <cmath>
#include <iomanip>
#include <istream>
#include <limits>
#include <locale>
#include <ostream>
#include <stdexcept>
#include <string>

namespace sensor_platform {
using namespace sensor_sandbox;
namespace {
constexpr float pi = 3.14159265359f;
constexpr int tickHz = 8;

// Explicit integer mixing avoids standard-library random distribution differences.
std::uint32_t mix(std::uint32_t value) {
    value ^= value >> 16;
    value *= 0x7feb352dU;
    value ^= value >> 15;
    value *= 0x846ca68bU;
    return value ^ (value >> 16);
}
float unit(std::uint32_t seed, int index, std::uint32_t salt) {
    return static_cast<float>(mix(seed ^ (static_cast<std::uint32_t>(index) * 0x9e3779b9U) ^ salt) & 0xffffffU) / 16777216.0f;
}
void validate(const ProceduralConfig& config) {
    if (config.durationSeconds < 4 || config.durationSeconds > 120 ||
        config.targetCount < 1 || config.targetCount > 12 ||
        config.sensorCount < 1 || config.sensorCount > 8)
        throw std::invalid_argument("Procedural duration must be 4..120 seconds, targets 1..12, sensors 1..8");
    for (const auto& parameter : proceduralParameters) {
        const float value = config.*(parameter.member);
        if (!std::isfinite(value) || value < parameter.minimum || value > parameter.maximum)
            throw std::invalid_argument(std::string(parameter.label) + " is outside its allowed range");
    }
    if (config.speedMin > config.speedMax)
        throw std::invalid_argument("Min speed must not exceed max speed");
}

void positionAt(Entity& entity, float time) {
    const float speed = entity.scenarioSpeed;
    float distance = speed * time;
    float forwardSpeed = speed;
    if (entity.scenarioMotion == ScenarioPathMotion::AccelerationBurst && time > entity.scenarioBurstTimeSeconds) {
        distance += speed * (entity.scenarioBurstMultiplier - 1) * (time - entity.scenarioBurstTimeSeconds);
        forwardSpeed *= entity.scenarioBurstMultiplier;
    }
    float lateral = 0, lateralSpeed = 0;
    const float amplitude = entity.scenarioLateralAmplitude;
    if (entity.scenarioMotion == ScenarioPathMotion::Arc) {
        const float phase = pi * distance / entity.scenarioTravelDistance;
        lateral = amplitude * std::sin(phase);
        lateralSpeed = amplitude * std::cos(phase) * pi * forwardSpeed / entity.scenarioTravelDistance;
    } else if (entity.scenarioMotion == ScenarioPathMotion::ZigZag) {
        // A triangle wave gives piecewise straight legs and deterministic turns.
        const float cycles = time * entity.scenarioFrequencyHz + entity.scenarioPhaseRadians / (2 * pi);
        const float phase = cycles - std::floor(cycles);
        lateral = amplitude * (1 - 4 * std::abs(phase - 0.5f));
        lateralSpeed = amplitude * entity.scenarioFrequencyHz * (phase < 0.5f ? 4 : -4);
    }
    const auto direction = entity.scenarioDirection;
    entity.position = {entity.scenarioStart.x + direction.x * distance - direction.y * lateral,
                       entity.scenarioStart.y + direction.y * distance + direction.x * lateral};
    entity.velocity = {direction.x * forwardSpeed - direction.y * lateralSpeed,
                       direction.y * forwardSpeed + direction.x * lateralSpeed};
    entity.headingRadians = std::atan2(entity.velocity.y, entity.velocity.x);
    entity.scenarioAgeSeconds = time;
}
}

ProceduralConfig readProceduralConfig(std::istream& input) {
    std::string header;
    std::getline(input, header);
    if (!header.empty() && header.back() == '\r') header.pop_back();
    if (header != "SENSOR_PROCEDURAL 1" && header != "SENSOR_PROCEDURAL 2")
        throw std::invalid_argument("Expected SENSOR_PROCEDURAL 1 or 2 header");
    auto number = [&]() {
        std::string token;
        std::uint32_t value{};
        if (!(input >> token)) throw std::invalid_argument("Missing procedural configuration value");
        const auto parsed = std::from_chars(token.data(), token.data() + token.size(), value);
        if (parsed.ec != std::errc{} || parsed.ptr != token.data() + token.size())
            throw std::invalid_argument("Expected unsigned 32-bit procedural configuration value");
        return value;
    };
    ProceduralConfig config;
    config.scenarioSeed = number();
    config.layoutSeed = number();
    const auto duration = number(), targets = number(), sensors = number();
    if (duration > 120 || targets > 12 || sensors > 8) throw std::invalid_argument("Procedural configuration exceeds limits");
    config.durationSeconds = static_cast<int>(duration);
    config.targetCount = static_cast<int>(targets);
    config.sensorCount = static_cast<int>(sensors);
    if (header == "SENSOR_PROCEDURAL 2") for (const auto& parameter : proceduralParameters) {
        std::string token;
        float value{};
        if (!(input >> token)) throw std::invalid_argument("Missing procedural parameter");
        const auto parsed = std::from_chars(token.data(), token.data()+token.size(), value);
        if (parsed.ec != std::errc{} || parsed.ptr != token.data()+token.size())
            throw std::invalid_argument("Expected numeric procedural parameter");
        config.*(parameter.member) = value;
    }
    std::string extra;
    if (input >> extra || input.bad()) throw std::invalid_argument("Unexpected procedural configuration data");
    validate(config);
    return config;
}

GeneratedScenario generateScenario(const ProceduralConfig& config) {
    validate(config);
    GeneratedScenario result{config, {}, {}};
    SensorScenario paths;
    paths.seed = config.scenarioSeed;
    paths.spawn.spawnRadius = 150 * config.spawnSpread;
    paths.spawn.passOffsetRadius = 25;
    paths.spawn.speed = {config.speedMin * 20 / config.durationSeconds, config.speedMax * 20 / config.durationSeconds};
    paths.spawn.amplitude = {12 * config.maneuver, 24 * config.maneuver};
    paths.spawn.frequencyHz = {std::max(.25f, config.maneuver) / config.durationSeconds,
                              1.5f * std::max(.25f, config.maneuver) / config.durationSeconds};
    paths.spawn.burstTimeSeconds = {0.45f * config.durationSeconds, 0.55f * config.durationSeconds};
    paths.spawn.burstMultiplier = {1 + .3f * config.maneuver, 1 + .5f * config.maneuver};
    // Rotate a balanced motion mix with the seed, rather than accidentally
    // generating four identical behaviors in the curated four-target case.
    const ScenarioPathMotion modes[]{ScenarioPathMotion::Linear, ScenarioPathMotion::Arc,
        ScenarioPathMotion::ZigZag, ScenarioPathMotion::AccelerationBurst};
    paths.spawn.motionTypes.clear();
    for (int i = 0; i < 4; ++i) paths.spawn.motionTypes.push_back(modes[(i + mix(config.scenarioSeed) % 4) % 4]);
    for (int id = 1; id <= config.targetCount; ++id) {
        auto path = ProceduralSpawnSystem{}.generatePath(paths, id, {});
        // Stratify approach angles so seeds cannot place every target on one
        // approach. Rotate the core-generated path, preserving its pass offset.
        const float angle = 2 * pi * (unit(config.scenarioSeed, 0, 9) +
            (id - 1 + 0.2f * (unit(config.scenarioSeed, id, 10) - 0.5f)) / config.targetCount);
        const float rotationAngle = angle - std::atan2(path.start.y, path.start.x);
        auto rotate = [&](Vec2 point) -> Vec2 {
            return {point.x * std::cos(rotationAngle) - point.y * std::sin(rotationAngle),
                    point.x * std::sin(rotationAngle) + point.y * std::cos(rotationAngle)};
        };
        path.start = rotate(path.start);
        path.direction = rotate(path.direction);
        // Low interaction turns approaches into dispersed, roughly tangential
        // routes. This uses only the target seed, never sensor-network randomness.
        const float divergence = (1 - config.convergence) * pi * .5f *
            (unit(config.scenarioSeed, id, 11) < .5f ? -1 : 1);
        if (divergence != 0) {
            const auto direction = path.direction;
            path.direction = {direction.x * std::cos(divergence) - direction.y * std::sin(divergence),
                              direction.x * std::sin(divergence) + direction.y * std::cos(divergence)};
        }
        Entity entity;
        entity.id = id;
        entity.label = "Procedural target " + std::to_string(id);
        entity.scenarioManaged = true;
        entity.scenarioStart = path.start;
        entity.scenarioDirection = path.direction;
        entity.scenarioTravelDistance = path.travelDistance;
        entity.scenarioSpeed = path.speed;
        entity.scenarioMotion = path.motion;
        entity.scenarioLateralAmplitude = path.lateralAmplitude;
        entity.scenarioFrequencyHz = path.frequencyHz;
        entity.scenarioPhaseRadians = path.phaseRadians;
        entity.scenarioBurstTimeSeconds = path.burstTimeSeconds;
        entity.scenarioBurstMultiplier = path.burstMultiplier;
        positionAt(entity, 0);
        result.entities.push_back(entity);
    }
    const float rotation = 2 * pi * unit(config.layoutSeed, 0, 1);
    const int rateOffset = static_cast<int>(mix(config.layoutSeed) % 3);
    // Bound the first half of every possible path for this target configuration,
    // without consulting target seeds/counts. Convexity makes endpoint distances
    // sufficient for the forward-distance/lateral-amplitude rectangle.
    const float spawnRadius = paths.spawn.spawnRadius;
    const float amplitude = 24 * config.maneuver;
    const float approach = std::atan2(25.0f, spawnRadius) + (1-config.convergence)*pi*.5f;
    const float halfDistance = config.speedMax * (10 + .5f * config.maneuver);
    const float lateralBound = 2 * amplitude * spawnRadius * std::min(1.0f, approach) + amplitude*amplitude;
    const float observationDisk = std::sqrt(std::max(spawnRadius*spawnRadius,
        spawnRadius*spawnRadius + halfDistance*halfDistance -
        2*spawnRadius*halfDistance*std::cos(approach)) + lateralBound) + 2;
    for (int i = 0; i < config.sensorCount; ++i) {
        SensorConfig sensor;
        sensor.id = i + 1;
        const float angle = rotation + 2 * pi * (i + 0.15f * (unit(config.layoutSeed, i, 2) - 0.5f)) / config.sensorCount;
        const float radius = (55 + 25 * unit(config.layoutSeed, i, 3)) * config.layoutSpread;
        sensor.position = {radius * std::cos(angle), radius * std::sin(angle)};
        // A coverage floor preserves useful observation even for dispersed paths.
        sensor.definition.range = std::max(radius + observationDisk,
            (radius + 170 + 20 * unit(config.layoutSeed, i, 4)) * config.coverage);
        const int quality = (i + rateOffset) % 3;
        sensor.definition.refreshRateHz = static_cast<float>(1 << quality);
        sensor.definition.rangeNoise = (0.3f + 0.65f * quality + 0.3f * unit(config.layoutSeed, i, 5)) * config.noise;
        sensor.definition.detectionProbability = (0.98f - 0.07f * quality) * config.reliability;
        sensor.definition.falsePositiveRateHz = (0.05f + 0.1f * quality) * config.clutter;
        sensor.seed = mix(config.layoutSeed ^ (static_cast<std::uint32_t>(i + 1) * 0x9e3779b9U));
        result.sensors.push_back(sensor);
    }
    return result;
}

void updateProceduralMotion(WorldState& world, float timeSeconds) {
    for (auto& entity : world.entities()) if (entity.scenarioManaged) positionAt(entity, timeSeconds);
}

void writeScenarioLayout(std::ostream& output, const GeneratedScenario& scenario) {
    output.imbue(std::locale::classic());
    output << std::setprecision(std::numeric_limits<float>::max_digits10) << "SENSOR_LAYOUT 1\n";
    for (const auto& sensor : scenario.sensors)
        output << "0 " << sensor.id << ' ' << sensor.position.x << ' ' << sensor.position.y
               << " 0 360 " << sensor.definition.range << '\n';
    if (!output) throw std::runtime_error("Cannot write generated sensor layout");
}

void runProcedural(RunId runId, const GeneratedScenario& scenario, const EventSink& sink) {
    validate(scenario.config);
    RunSession session(runId, scenario.entities, scenario.sensors);
    for (const auto& event : session.start()) sink(event);
    for (int tick = 0; tick <= scenario.config.durationSeconds * tickHz; ++tick)
        for (const auto& event : session.advanceTo(static_cast<float>(tick) / tickHz)) sink(event);
    sink(session.finish());
}
}
