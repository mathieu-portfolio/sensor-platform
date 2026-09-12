#include "MultiSensorRunner.hpp"
#include "ProceduralScenario.hpp"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

#include "sensor/world/EntityMotionSystem.hpp"

namespace sensor_platform {

MultiSensorRunner::MultiSensorRunner(std::vector<sensor_sandbox::Entity> entities,
                                   const std::vector<SensorConfig>& configs) {
    world_.entities() = std::move(entities);
    for (const auto& config : configs) {
        const auto& d = config.definition;
        if (std::any_of(world_.sensors().begin(), world_.sensors().end(),
                        [&](const auto& sensor) { return sensor.id == config.id; })) {
            throw std::invalid_argument("Sensor IDs must be unique");
        }
        if (!std::isfinite(config.position.x) || !std::isfinite(config.position.y) ||
            !std::isfinite(config.headingRadians) ||
            !std::isfinite(d.refreshRateHz) || d.refreshRateHz <= 0 ||
            !std::isfinite(1.0f / d.refreshRateHz) ||
            !std::isfinite(d.range) || d.range < 0 ||
            !std::isfinite(d.fieldOfViewRadians) || d.fieldOfViewRadians <= 0 ||
            d.fieldOfViewRadians > 6.28318530718f ||
            !std::isfinite(d.rangeNoise) || d.rangeNoise < 0 ||
            !std::isfinite(d.detectionProbability) || d.detectionProbability < 0 || d.detectionProbability > 1 ||
            !std::isfinite(d.falsePositiveRateHz) || d.falsePositiveRateHz < 0) {
            throw std::invalid_argument("Invalid sensor position, cadence, coverage or noise configuration");
        }
        sensor_sandbox::Sensor sensor;
        sensor.id = config.id;
        sensor.position = config.position;
        sensor.headingRadians = config.headingRadians;
        sensor.definition = d;
        world_.sensors().push_back(std::move(sensor));
        scanners_.emplace_back(config.seed);
        enabled_.push_back(true);
    }
}

std::vector<sensor_sandbox::SensorScan> MultiSensorRunner::advanceTo(float simulationTimeSeconds) {
    if (!std::isfinite(simulationTimeSeconds) || simulationTimeSeconds < timeSeconds_) {
        throw std::invalid_argument("Runner time must be finite, nonnegative and nondecreasing");
    }
    if (simulationTimeSeconds > timeSeconds_) {
        sensor_sandbox::EntityMotionSystem{}.update(world_, simulationTimeSeconds - timeSeconds_);
        updateProceduralMotion(world_, simulationTimeSeconds);
    }
    timeSeconds_ = simulationTimeSeconds;
    std::vector<sensor_sandbox::SensorScan> scans;
    for (std::size_t i = 0; i < scanners_.size(); ++i) {
        if (!enabled_[i]) continue;
        if (auto scan = scanners_[i].scan(world_.sensors()[i], world_.entities(), timeSeconds_)) {
            scans.push_back(std::move(*scan));
        }
    }
    return scans;
}

void MultiSensorRunner::setSensorEnabled(sensor_sandbox::SensorId id, bool enabled) {
    for (std::size_t i = 0; i < scanners_.size(); ++i) {
        if (world_.sensors()[i].id == id) {
            enabled_[i] = enabled;
            return;
        }
    }
    throw std::invalid_argument("Unknown sensor ID");
}

void MultiSensorRunner::resetSensor(sensor_sandbox::SensorId id) {
    for (std::size_t i = 0; i < scanners_.size(); ++i) {
        if (world_.sensors()[i].id == id) {
            scanners_[i].reset();
            return;
        }
    }
    throw std::invalid_argument("Unknown sensor ID");
}

} // namespace sensor_platform
