#pragma once

#include <iosfwd>
#include <array>
#include "EventTransport.hpp"
#include "MultiSensorRunner.hpp"

namespace sensor_platform {
// Version 1 uses fixed 8 Hz simulation ticks and an origin-centred observation area.
struct ProceduralConfig {
    std::uint32_t scenarioSeed{2026};
    std::uint32_t layoutSeed{73};
    int durationSeconds{20};
    int targetCount{4};
    int sensorCount{3};
    float speedMin{14}, speedMax{16}; // m/s at 20 s; scaled by 20/duration.
    float maneuver{1}, convergence{1}, spawnSpread{1};
    float coverage{1}, layoutSpread{1}, noise{1}, reliability{1}, clutter{1};
};

struct ProceduralParameter {
    const char* label;
    float ProceduralConfig::* member;
    float minimum, maximum;
};
inline constexpr std::array<ProceduralParameter, 10> proceduralParameters{{
    {"Min speed", &ProceduralConfig::speedMin, 1, 30},
    {"Max speed", &ProceduralConfig::speedMax, 1, 30},
    {"Maneuver", &ProceduralConfig::maneuver, 0, 3},
    {"Convergence", &ProceduralConfig::convergence, 0, 1},
    {"Spawn spread", &ProceduralConfig::spawnSpread, .4f, 1.5f},
    {"Coverage", &ProceduralConfig::coverage, .65f, 1.6f},
    {"Layout spread", &ProceduralConfig::layoutSpread, .25f, 3},
    {"Noise", &ProceduralConfig::noise, 0, 5},
    {"Reliability", &ProceduralConfig::reliability, .35f, 1},
    {"Clutter", &ProceduralConfig::clutter, 0, 12},
}};

struct GeneratedScenario {
    ProceduralConfig config;
    std::vector<sensor_sandbox::Entity> entities;
    std::vector<SensorConfig> sensors;
};

ProceduralConfig readProceduralConfig(std::istream& input);
GeneratedScenario generateScenario(const ProceduralConfig& config);
void writeScenarioLayout(std::ostream& output, const GeneratedScenario& scenario);
void runProcedural(sensor_sandbox::RunId runId, const GeneratedScenario& scenario, const EventSink& sink);
// Absolute-time execution of the core's generated path descriptors. Unmanaged
// entities retain the runner's existing core constant-velocity/bounce behavior.
void updateProceduralMotion(sensor_sandbox::WorldState& world, float timeSeconds);
}
