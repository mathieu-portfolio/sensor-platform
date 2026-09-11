#pragma once

#include <map>

#include "MultiSensorRunner.hpp"
#include "sensor/events/StreamEvent.hpp"

namespace sensor_platform {

// Live event producer. Lifecycle calls are explicit; persistence is separate.
class RunSession {
public:
    RunSession(sensor_sandbox::RunId runId, std::vector<sensor_sandbox::Entity> entities,
               std::vector<SensorConfig> configs);
    std::vector<sensor_sandbox::StreamEvent> start();
    std::vector<sensor_sandbox::StreamEvent> advanceTo(float timeSeconds);
    sensor_sandbox::StreamEvent resetSensor(sensor_sandbox::SensorId id);
    void setSensorEnabled(sensor_sandbox::SensorId id, bool enabled);
    std::vector<sensor_sandbox::StreamEvent> resetRun();
    sensor_sandbox::StreamEvent finish();

private:
    sensor_sandbox::StreamEvent event(sensor_sandbox::SensorEventPayload payload);
    void requireActive() const;
    void sensorStarts(std::vector<sensor_sandbox::StreamEvent>& events);

    sensor_sandbox::RunId runId_;
    std::vector<sensor_sandbox::Entity> initialEntities_;
    std::vector<SensorConfig> configs_;
    MultiSensorRunner runner_;
    std::map<sensor_sandbox::SensorId, std::uint64_t> sensorGenerations_;
    std::uint64_t generation_{};
    std::uint64_t sequence_{};
    float timeSeconds_{};
    bool started_{};
    bool finished_{};
};

} // namespace sensor_platform
