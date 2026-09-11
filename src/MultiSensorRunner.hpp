#pragma once

#include <cstdint>
#include <vector>

#include "sensor/sensors/SensorSystem.hpp"
#include "sensor/world/WorldState.hpp"

namespace sensor_platform {

struct SensorConfig {
    sensor_sandbox::SensorId id{};
    sensor_sandbox::Vec2 position{};
    float headingRadians{};
    // Range, FOV, refreshRateHz, rangeNoise, detectionProbability, falsePositiveRateHz.
    sensor_sandbox::SensorDefinition definition;
    std::uint32_t seed{};
};

class MultiSensorRunner {
public:
    // Entities start at simulation time zero; sensor configs must have unique IDs.
    MultiSensorRunner(std::vector<sensor_sandbox::Entity> entities, const std::vector<SensorConfig>& configs);

    // Advance world once, then observe it with each sensor. Finite/nondecreasing time.
    // Completed scans (including empty ones) follow configuration order; not-due omitted.
    std::vector<sensor_sandbox::SensorScan> advanceTo(float simulationTimeSeconds);
    // Next poll is immediately due at the shared time; world and other streams continue.
    void resetSensor(sensor_sandbox::SensorId id);
    // Disabled polls do not touch deadlines, sequences or RNG state. No missed-scan replay.
    void setSensorEnabled(sensor_sandbox::SensorId id, bool enabled);
    const sensor_sandbox::WorldState& world() const { return world_; }

private:
    sensor_sandbox::WorldState world_;
    std::vector<sensor_sandbox::SensorSystem> scanners_;
    std::vector<bool> enabled_;
    float timeSeconds_{};
};

} // namespace sensor_platform
