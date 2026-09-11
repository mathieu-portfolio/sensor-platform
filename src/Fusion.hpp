#pragma once
#include <map>
#include <set>
#include <string>
#include "EventRecording.hpp"

namespace sensor_platform {

struct WorldObservation {
    sensor_sandbox::SensorId sensorId{};
    std::uint64_t sensorGeneration{}, scanSequence{};
    sensor_sandbox::DetectionId detectionId{}; // Measurement identity only, never an entity association.
    double time{}, x{}, y{}, confidence{}, uncertaintyRadius{};
};
// Current detections are already world Cartesian coordinates, in sandbox world units.
std::vector<WorldObservation> worldObservations(const sensor_sandbox::StreamEvent& event);

struct FusionConfig {
    double gateDistance{20};
    double positionGain{0.8};
    double velocityGain{0.2};
    double coastAfter{0.5};
    double deleteAfter{2};
    double tentativeTimeout{1};
    unsigned confirmationTimes{2}; // Distinct acquisition timestamps, not simultaneous radar hits.
};

struct GlobalTrack {
    std::uint64_t id{};
    double x{}, y{}, vx{}, vy{}, lastSeen{};
    std::uint64_t observations{}, distinctTimes{};
    std::string state;
    std::vector<sensor_sandbox::SensorId> sensors; // Lifetime contributors, not claimed current visibility.
};
struct TrackAssociation { WorldObservation observation; std::uint64_t trackId{}; };
struct RetiredTrack { std::uint64_t trackId{}; std::string reason; };
struct GlobalTrackEvent {
    sensor_sandbox::EventIdentity source;
    std::string sourceType;
    std::vector<GlobalTrack> tracks; // Complete active snapshot at source.timeSeconds, sorted by ID.
    std::vector<TrackAssociation> associations;
    std::vector<RetiredTrack> retired;
};

// Validates ordered input; no truth/evaluation types in this processor or its output.
class FusionSystem {
public:
    explicit FusionSystem(FusionConfig config = {});
    GlobalTrackEvent accept(const sensor_sandbox::StreamEvent& event);
    void finish() const { validator_.finish(); }
    const FusionConfig& config() const { return config_; }
private:
    struct Track {
        std::uint64_t id{}, observations{}, distinctTimes{};
        double x{}, y{}, vx{}, vy{}, lastSeen{};
        std::set<sensor_sandbox::SensorId> sensors;
    };
    FusionConfig config_;
    EventValidator validator_;
    std::map<std::uint64_t, Track> tracks_;
    std::uint64_t nextId_{1};
};

void printGlobalTrackEvent(std::ostream& output, const GlobalTrackEvent& event, const FusionConfig& config);
// CLI helper: file input validates fully before output; '-' processes a live stdin prefix.
int fusionCommand(int argc, char** argv);
}
