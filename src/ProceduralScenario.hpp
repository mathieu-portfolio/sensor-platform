#pragma once

#include <iosfwd>
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
};

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
