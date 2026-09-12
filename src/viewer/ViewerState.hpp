#pragma once
#include "Fusion.hpp"
#include <deque>
#include <istream>

namespace sensor_platform::viewer {
struct SensorGeometry {
    std::uint64_t generation{};
    sensor_sandbox::SensorId id{};
    double x{}, y{}, headingDegrees{}, fovDegrees{}, range{};
};
// Optional display annotations, never supplied to simulation or fusion.
std::vector<SensorGeometry> readLayout(std::istream& input);

struct SensorView {
    std::uint64_t generation{}, scans{}, measurements{};
    std::vector<WorldObservation> latest;
};
struct Point { double x{}, y{}; };
class State {
public:
    void accept(const sensor_sandbox::StreamEvent& event);
    sensor_sandbox::EventIdentity source{};
    std::map<sensor_sandbox::SensorId, SensorView> sensors;
    GlobalTrackEvent snapshot;
    std::map<std::uint64_t, std::deque<Point>> histories;
    std::uint64_t events{}, scans{}, measurements{}; // Whole playback, across resets.
    bool finished{};
    static constexpr std::size_t historyLimit = 32;
private:
    FusionSystem fusion_;
};

// Wall time only schedules recorded events; it never advances simulation or fusion.
class Playback {
public:
    explicit Playback(std::vector<sensor_sandbox::StreamEvent> events);
    void advance(double seconds);
    void step();
    void stepBackward();
    void restart();
    const State& state() const { return state_; }
    bool done() const { return next_ == events_.size(); }
    std::size_t size() const { return events_.size(); }
private:
    std::vector<sensor_sandbox::StreamEvent> events_;
    std::vector<double> due_;
    std::size_t next_{};
    double clock_{};
    State state_;
};
}
