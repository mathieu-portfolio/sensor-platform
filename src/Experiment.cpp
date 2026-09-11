#include "Experiment.hpp"
#include "RunSession.hpp"
#include <chrono>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <thread>

namespace sensor_platform {
void runExperiment(sensor_sandbox::RunId runId, const std::string& path, const EventSink& sink) {
    std::ifstream input(path);
    std::string header;
    std::getline(input, header);
    int ticks{}, tickHz{};
    double wallScale{};
    if (header != "SENSOR_EXPERIMENT 1" || !(input >> ticks >> tickHz >> wallScale) ||
        ticks < 1 || ticks > 10000000 || tickHz < 1 || tickHz > 10000 ||
        !std::isfinite(wallScale) || wallScale < 0 || wallScale > 100)
        throw std::invalid_argument("Invalid experiment header/timing");
    std::vector<SensorConfig> configs;
    struct Outage { int id; float start, end; };
    std::vector<Outage> outages;
    std::string kind;
    while (input >> kind) {
        if (kind == "SENSOR") {
            SensorConfig config;
            if (!(input >> config.id >> config.position.x >> config.position.y >> config.definition.refreshRateHz >> config.seed))
                throw std::invalid_argument("Invalid experiment sensor");
            config.definition.range = 1000;
            config.definition.rangeNoise = 2;
            config.definition.detectionProbability = 0.9f;
            if (config.definition.refreshRateHz > tickHz)
                throw std::invalid_argument("Scan frequency exceeds polling frequency");
            configs.push_back(config);
        } else if (kind == "OUTAGE") {
            Outage outage{};
            if (!(input >> outage.id >> outage.start >> outage.end) || !std::isfinite(outage.start) ||
                !std::isfinite(outage.end) || outage.start < 0 || outage.end <= outage.start ||
                outage.end > static_cast<float>(ticks) / tickHz)
                throw std::invalid_argument("Invalid outage interval");
            outages.push_back(outage);
        } else throw std::invalid_argument("Unknown experiment record");
    }
    if (configs.empty() || configs.size() > 1000) throw std::invalid_argument("Expected 1..1000 sensors");
    sensor_sandbox::Entity entity;
    entity.id = 1;
    entity.position = {100, 0};
    entity.velocity = {10, 0};
    RunSession session(runId, {entity}, configs);
    // Reject unknown outage IDs before emitting a prefix.
    for (const auto& outage : outages)
        if (std::none_of(configs.begin(), configs.end(), [&](const auto& c) { return c.id == outage.id; }))
            throw std::invalid_argument("Unknown outage sensor ID");
    for (const auto& event : session.start()) sink(event);
    const auto origin = std::chrono::steady_clock::now();
    for (int tick = 0; tick <= ticks; ++tick) {
        const float time = static_cast<float>(tick) / tickHz;
        if (wallScale > 0)
            std::this_thread::sleep_until(origin + std::chrono::duration<double>(static_cast<double>(tick) / tickHz * wallScale));
        for (const auto& config : configs) {
            bool enabled = true;
            for (const auto& outage : outages)
                if (outage.id == config.id && time >= outage.start && time < outage.end) enabled = false;
            session.setSensorEnabled(config.id, enabled);
        }
        for (const auto& event : session.advanceTo(time)) sink(event);
    }
    sink(session.finish());
}

Observation::Observation(const ObservationOptions& options) : options_(options) {
    if (options.delayMs < 0 || options.pauseMs < 0 || bool(options.pauseAfter) != bool(options.pauseMs))
        throw std::invalid_argument("Invalid consumer delay/pause");
    if (!options.metrics.empty()) {
        output_.open(options.metrics, std::ios::trunc);
        if (!output_) throw std::runtime_error("Cannot create metrics file");
        output_ << "phase,sequence,wall_ns\n";
    }
}
void Observation::mark(const char* phase, std::uint64_t sequence) {
    if (!output_.is_open()) return;
    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    output_ << phase << ',' << sequence << ',' << ns << '\n';
    output_.flush();
    if (!output_) throw std::runtime_error("Metrics write failed");
}
void Observation::beforeConsume() {
    if (options_.pauseAfter && consumed_ == options_.pauseAfter) {
        mark("pause", consumed_);
        std::this_thread::sleep_for(std::chrono::milliseconds(options_.pauseMs));
        mark("resume", consumed_);
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(options_.delayMs));
    ++consumed_;
}
}
