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
    if (header != "SENSOR_PROCEDURAL 1") throw std::invalid_argument("Expected SENSOR_PROCEDURAL 1 header");
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
    paths.spawn.spawnRadius = 150;
    paths.spawn.passOffsetRadius = 25;
    paths.spawn.speed = {280.0f / config.durationSeconds, 320.0f / config.durationSeconds};
    paths.spawn.amplitude = {12, 24};
    paths.spawn.frequencyHz = {1.0f / config.durationSeconds, 1.5f / config.durationSeconds};
    paths.spawn.burstTimeSeconds = {0.45f * config.durationSeconds, 0.55f * config.durationSeconds};
    paths.spawn.burstMultiplier = {1.3f, 1.5f};
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
    for (int i = 0; i < config.sensorCount; ++i) {
        SensorConfig sensor;
        sensor.id = i + 1;
        const float angle = rotation + 2 * pi * (i + 0.15f * (unit(config.layoutSeed, i, 2) - 0.5f)) / config.sensorCount;
        const float radius = 55 + 25 * unit(config.layoutSeed, i, 3);
        sensor.position = {radius * std::cos(angle), radius * std::sin(angle)};
        // Every radar covers the radius-170 observation disk independently of
        // target seed/count. Targets start inside it and converge through it.
        sensor.definition.range = radius + 170 + 20 * unit(config.layoutSeed, i, 4);
        const int quality = (i + rateOffset) % 3;
        sensor.definition.refreshRateHz = static_cast<float>(1 << quality);
        sensor.definition.rangeNoise = 0.3f + 0.65f * quality + 0.3f * unit(config.layoutSeed, i, 5);
        sensor.definition.detectionProbability = 0.98f - 0.07f * quality;
        sensor.definition.falsePositiveRateHz = 0.05f + 0.1f * quality;
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
