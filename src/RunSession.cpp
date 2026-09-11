#include "RunSession.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace sensor_platform {
using namespace sensor_sandbox;

namespace {
std::vector<SensorConfig> ordered(std::vector<SensorConfig> configs) {
    std::sort(configs.begin(), configs.end(), [](const auto& a, const auto& b) { return a.id < b.id; });
    return configs;
}
}

RunSession::RunSession(RunId runId, std::vector<Entity> entities, std::vector<SensorConfig> configs)
    : runId_(runId), initialEntities_(std::move(entities)), configs_(ordered(std::move(configs))),
      runner_(initialEntities_, configs_) {
    if (runId == 0) throw std::invalid_argument("Run ID must be nonzero");
}

StreamEvent RunSession::event(SensorEventPayload payload) {
    return {{runId_, generation_, ++sequence_, timeSeconds_}, std::move(payload)};
}

void RunSession::requireActive() const {
    if (!started_ || finished_) throw std::logic_error("Run must be started and not finished");
}

void RunSession::sensorStarts(std::vector<StreamEvent>& events) {
    sensorGenerations_.clear();
    for (const auto& config : configs_) {
        sensorGenerations_[config.id] = 0;
        events.push_back(event(SensorStarted{config.id, 0, config.seed}));
    }
}

std::vector<StreamEvent> RunSession::start() {
    if (started_) throw std::logic_error("Run already started");
    started_ = true;
    std::vector<StreamEvent> events{event(RunStarted{})};
    sensorStarts(events);
    return events;
}

std::vector<StreamEvent> RunSession::advanceTo(float timeSeconds) {
    requireActive();
    auto scans = runner_.advanceTo(timeSeconds);
    timeSeconds_ = timeSeconds;
    std::vector<StreamEvent> events;
    for (auto& scan : scans) {
        events.push_back(event(RadarMeasurements{scan.sensorId, sensorGenerations_.at(scan.sensorId),
                                                scan.sequence, std::move(scan.detections)}));
    }
    return events;
}

StreamEvent RunSession::resetSensor(SensorId id) {
    requireActive();
    runner_.resetSensor(id);
    return event(SensorReset{id, ++sensorGenerations_.at(id)});
}

std::vector<StreamEvent> RunSession::resetRun() {
    requireActive();
    runner_ = MultiSensorRunner(initialEntities_, configs_);
    ++generation_;
    timeSeconds_ = 0;
    std::vector<StreamEvent> events{event(RunReset{})};
    sensorStarts(events);
    return events;
}

StreamEvent RunSession::finish() {
    requireActive();
    finished_ = true;
    return event(RunFinished{});
}

} // namespace sensor_platform
