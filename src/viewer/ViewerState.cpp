#include "ViewerState.hpp"
#include <cmath>
#include <sstream>
#include <stdexcept>

namespace sensor_platform::viewer {
using namespace sensor_sandbox;
std::vector<SensorGeometry> readLayout(std::istream& input) {
    std::string line;
    if (!std::getline(input, line)) throw std::invalid_argument("Missing SENSOR_LAYOUT 1 header");
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line != "SENSOR_LAYOUT 1") throw std::invalid_argument("Expected SENSOR_LAYOUT 1 header");
    std::vector<SensorGeometry> result;
    std::set<std::pair<std::uint64_t, SensorId>> keys;
    std::size_t number = 1;
    while (std::getline(input, line)) {
        ++number;
        if (line.empty() || line[0] == '#') continue;
        std::istringstream row(line);
        SensorGeometry geometry;
        std::string extra;
        if (line.find_first_not_of(" \t\r") == std::string::npos) continue;
        const auto first = line.find_first_not_of(" \t");
        if (line[first] == '-' ||
            !(row >> geometry.generation >> geometry.id >> geometry.x >> geometry.y
                  >> geometry.headingDegrees >> geometry.fovDegrees >> geometry.range) || row >> extra ||
            !std::isfinite(geometry.x) || !std::isfinite(geometry.y) ||
            !std::isfinite(geometry.headingDegrees) || !std::isfinite(geometry.fovDegrees) ||
            !std::isfinite(geometry.range) || geometry.range <= 0 ||
            std::abs(geometry.x) > 1e12 || std::abs(geometry.y) > 1e12 || geometry.range > 1e12 ||
            geometry.fovDegrees <= 0 || geometry.fovDegrees > 360 ||
            !keys.emplace(geometry.generation, geometry.id).second)
            throw std::invalid_argument("Invalid/duplicate sensor layout at line " + std::to_string(number));
        result.push_back(geometry);
    }
    if (input.bad()) throw std::runtime_error("Failed to read sensor layout");
    return result;
}

void State::accept(const StreamEvent& event) {
    auto output = fusion_.accept(event); // Authoritative order validation before viewer mutation.
    if (std::holds_alternative<RunReset>(event.payload)) {
        sensors.clear();
        histories.clear();
    }
    if (const auto* started = std::get_if<SensorStarted>(&event.payload))
        sensors.emplace(started->sensorId, SensorView{});
    if (const auto* reset = std::get_if<SensorReset>(&event.payload))
        sensors.at(reset->sensorId) = SensorView{reset->sensorGeneration};
    if (const auto* scan = std::get_if<RadarMeasurements>(&event.payload)) {
        auto& sensor = sensors.at(scan->sensorId);
        sensor.latest = worldObservations(event);
        ++sensor.scans;
        sensor.measurements += scan->detections.size();
        ++scans;
        measurements += scan->detections.size();
    }
    for (const auto& retired : output.retired) histories.erase(retired.trackId);
    for (const auto& track : output.tracks) {
        auto& history = histories[track.id];
        if (history.empty() || history.back().x != track.x || history.back().y != track.y)
            history.push_back({track.x, track.y});
        if (history.size() > historyLimit) history.pop_front();
    }
    source = event.identity;
    snapshot = std::move(output);
    ++events;
    finished = std::holds_alternative<RunFinished>(event.payload);
}

Playback::Playback(std::vector<StreamEvent> events) : events_(std::move(events)) {
    validateEvents(events_);
    double due = 0;
    for (std::size_t i = 0; i < events_.size(); ++i) {
        if (i && events_[i].identity.runGeneration == events_[i-1].identity.runGeneration)
            due += events_[i].identity.timeSeconds - events_[i-1].identity.timeSeconds;
        due_.push_back(due);
    }
}
void Playback::advance(double seconds) {
    if (!std::isfinite(seconds) || seconds < 0) throw std::invalid_argument("Invalid playback elapsed time");
    clock_ += seconds;
    while (!done() && due_[next_] <= clock_) state_.accept(events_[next_++]);
}
void Playback::step() {
    if (done()) return;
    clock_ = due_[next_];
    state_.accept(events_[next_++]);
}
void Playback::stepBackward() {
    if (next_ == 0) return;
    const auto target = next_ - 1;
    // Rebuild all fusion internals, counters and histories from the exact prefix.
    restart();
    while (next_ < target) step();
}
void Playback::restart() { next_ = 0; clock_ = 0; state_ = State{}; }

void PlaybackSession::replaceRecording(std::vector<StreamEvent> events) {
    Playback next(std::move(events));
    next.advance(0);
    playback = std::move(next);
    paused = false;
}
}
