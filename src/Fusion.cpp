#include "Fusion.hpp"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <limits>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <tuple>

namespace sensor_platform {
using namespace sensor_sandbox;

std::vector<WorldObservation> worldObservations(const StreamEvent& event) {
    std::vector<WorldObservation> result;
    if (const auto* scan = std::get_if<RadarMeasurements>(&event.payload))
        for (const auto& d : scan->detections)
            result.push_back({scan->sensorId, scan->sensorGeneration, scan->scanSequence, d.id,
                              event.identity.timeSeconds, d.estimatedPosition.x, d.estimatedPosition.y,
                              d.confidence, d.uncertaintyRadius});
    return result;
}

FusionSystem::FusionSystem(FusionConfig config) : config_(config) {
    if (!std::isfinite(config.gateDistance) || config.gateDistance <= 0 || config.gateDistance > 1e9 ||
        !std::isfinite(config.positionGain) || config.positionGain <= 0 || config.positionGain > 1 ||
        !std::isfinite(config.velocityGain) || config.velocityGain < 0 || config.velocityGain > 1 ||
        !std::isfinite(config.coastAfter) || config.coastAfter < 0 ||
        !std::isfinite(config.deleteAfter) || config.deleteAfter <= config.coastAfter ||
        !std::isfinite(config.tentativeTimeout) || config.tentativeTimeout <= 0 || !config.confirmationTimes)
        throw std::invalid_argument("Invalid fusion gate/gains/lifecycle configuration");
}

GlobalTrackEvent FusionSystem::accept(const StreamEvent& event) {
    validator_.accept(event); // Rejected duplicates/gaps/late events leave track state unchanged.
    GlobalTrackEvent output;
    output.source = event.identity;
    const double time = event.identity.timeSeconds;
    if (std::holds_alternative<RunStarted>(event.payload)) output.sourceType = "RUN_STARTED";
    else if (std::holds_alternative<RunReset>(event.payload)) output.sourceType = "RUN_RESET";
    else if (std::holds_alternative<RunFinished>(event.payload)) output.sourceType = "RUN_FINISHED";
    else if (std::holds_alternative<SensorStarted>(event.payload)) output.sourceType = "SENSOR_STARTED";
    else if (std::holds_alternative<SensorReset>(event.payload)) output.sourceType = "SENSOR_RESET";
    else output.sourceType = "MEASUREMENTS";
    if (output.sourceType == "RUN_RESET") {
        for (const auto& [id, track] : tracks_) output.retired.push_back({id, "run_reset"});
        tracks_.clear(); // IDs stay unique across this run's generations.
    } else {
        for (auto it = tracks_.begin(); it != tracks_.end();) {
            const auto& track = it->second;
            const double timeout = track.distinctTimes < config_.confirmationTimes ? config_.tentativeTimeout : config_.deleteAfter;
            if (time - track.lastSeen >= timeout) {
                output.retired.push_back({track.id, "timeout"});
                it = tracks_.erase(it);
            } else ++it;
        }
    }
    const auto observations = worldObservations(event);
    struct Candidate { double distance; std::uint64_t track; std::size_t observation; };
    std::vector<Candidate> candidates;
    for (const auto& [id, track] : tracks_) {
        const double dt = time - track.lastSeen;
        const double x = track.x + track.vx * dt, y = track.y + track.vy * dt;
        for (std::size_t i = 0; i < observations.size(); ++i) {
            const double distance = std::hypot(x - observations[i].x, y - observations[i].y);
            if (distance <= config_.gateDistance) candidates.push_back({distance, id, i});
        }
    }
    // Greedy global nearest pair per scan, one-to-one. Equal distances use stable IDs.
    std::sort(candidates.begin(), candidates.end(), [&](const auto& a, const auto& b) {
        return std::tuple(a.distance, a.track, observations[a.observation].detectionId) <
               std::tuple(b.distance, b.track, observations[b.observation].detectionId);
    });
    std::map<std::size_t, std::uint64_t> matches;
    std::set<std::uint64_t> used;
    for (const auto& c : candidates)
        if (!used.contains(c.track) && !matches.contains(c.observation)) {
            matches[c.observation] = c.track;
            used.insert(c.track);
        }
    for (std::size_t i = 0; i < observations.size(); ++i) {
        const auto& observation = observations[i];
        std::uint64_t id{};
        if (matches.contains(i)) {
            id = matches.at(i);
            auto& track = tracks_.at(id);
            const double dt = time - track.lastSeen;
            const double px = track.x + track.vx * dt, py = track.y + track.vy * dt;
            const double dx = observation.x - px, dy = observation.y - py;
            track.x = px + config_.positionGain * dx;
            track.y = py + config_.positionGain * dy;
            if (dt > 0) {
                // Bound the divisor for closely interleaved noisy radar observations.
                const double scale = config_.velocityGain / std::max(dt, 0.05);
                track.vx += scale * dx;
                track.vy += scale * dy;
                ++track.distinctTimes;
            }
            track.lastSeen = time;
            ++track.observations;
            track.sensors.insert(observation.sensorId);
        } else {
            id = nextId_++;
            tracks_.emplace(id, Track{id, 1, 1, observation.x, observation.y, 0, 0, time, {observation.sensorId}});
        }
        output.associations.push_back({observation, id});
    }
    for (const auto& [id, track] : tracks_) {
        const double dt = time - track.lastSeen;
        std::string state = track.distinctTimes < config_.confirmationTimes ? "tentative" :
                            dt > config_.coastAfter ? "coasting" : "confirmed";
        output.tracks.push_back({id, track.x + track.vx * dt, track.y + track.vy * dt, track.vx, track.vy,
                                 track.lastSeen, track.observations, track.distinctTimes, state,
                                 {track.sensors.begin(), track.sensors.end()}});
    }
    return output;
}

void printGlobalTrackEvent(std::ostream& output, const GlobalTrackEvent& event, const FusionConfig& config) {
    std::ostringstream s;
    s.imbue(std::locale::classic());
    s << std::setprecision(std::numeric_limits<double>::max_digits10);
    s << "{\"schema_version\":1,\"event_type\":\"GLOBAL_TRACKS\",\"run_id\":" << event.source.runId
      << ",\"run_generation\":" << event.source.runGeneration << ",\"source_sequence\":" << event.source.streamSequence
      << ",\"acquisition_time\":" << event.source.timeSeconds << ",\"source_type\":\"" << event.sourceType << '"';
    if (event.sourceType == "RUN_STARTED")
        s << ",\"coordinate_frame\":\"world_cartesian\",\"position_units\":\"sandbox_world_units\",\"time_units\":\"simulation_seconds\""
          << ",\"config\":{\"gate\":" << config.gateDistance << ",\"alpha\":" << config.positionGain
          << ",\"beta\":" << config.velocityGain << ",\"coast_after\":" << config.coastAfter
          << ",\"delete_after\":" << config.deleteAfter << ",\"tentative_timeout\":" << config.tentativeTimeout
          << ",\"confirmation_times\":" << config.confirmationTimes << '}';
    s << ",\"tracks\":[";
    bool comma = false;
    for (const auto& t : event.tracks) {
        if (comma) s << ',';
        comma = true;
        s << "{\"track_id\":" << t.id << ",\"state\":\"" << t.state << "\",\"x\":" << t.x << ",\"y\":" << t.y
          << ",\"vx\":" << t.vx << ",\"vy\":" << t.vy << ",\"last_seen\":" << t.lastSeen
          << ",\"observations\":" << t.observations << ",\"distinct_times\":" << t.distinctTimes << ",\"sensors\":[";
        for (std::size_t i = 0; i < t.sensors.size(); ++i) { if (i) s << ','; s << t.sensors[i]; }
        s << "]}";
    }
    s << "],\"associations\":[";
    comma = false;
    for (const auto& a : event.associations) {
        if (comma) s << ',';
        comma = true;
        s << "{\"sensor_id\":" << a.observation.sensorId << ",\"sensor_generation\":" << a.observation.sensorGeneration
          << ",\"scan_sequence\":" << a.observation.scanSequence << ",\"detection_id\":" << a.observation.detectionId
          << ",\"track_id\":" << a.trackId << '}';
    }
    s << "],\"retired\":[";
    comma = false;
    for (const auto& t : event.retired) { if (comma) s << ','; comma = true;
        s << "{\"track_id\":" << t.trackId << ",\"reason\":\"" << t.reason << "\"}"; }
    s << "]}\n";
    output << s.str();
    output.flush();
    if (!output) throw std::runtime_error("Failed to write global-track event");
}
}
