#include "Fusion.hpp"
#include <cmath>
#include <iostream>
#include <sstream>
#include <stdexcept>

using namespace sensor_platform;
using namespace sensor_sandbox;
namespace {
void check(bool yes, const char* message) { if (!yes) throw std::runtime_error(message); }
struct Input {
    std::uint64_t sequence{}, generation{}, scans[2]{}, sensorGenerations[2]{};
    int detections[2]{1, 1};
    StreamEvent event(float time, SensorEventPayload payload) { return {{42, generation, ++sequence, time}, std::move(payload)}; }
    void start(FusionSystem& fusion) {
        fusion.accept(event(0, RunStarted{}));
        fusion.accept(event(0, SensorStarted{1, 0, 7}));
        fusion.accept(event(0, SensorStarted{2, 0, 8}));
    }
    StreamEvent scan(float time, int sensor, std::vector<Vec2> positions) {
        RadarMeasurements scan{sensor, sensorGenerations[sensor-1], ++scans[sensor-1], {}};
        for (const auto& position : positions) scan.detections.push_back({detections[sensor-1]++, sensor, position, .9f, 2});
        return event(time, scan);
    }
};

void overlapAndAsynchrony() {
    FusionSystem fusion;
    Input input;
    input.start(fusion);
    const auto event = input.scan(0, 1, {{100, 20}});
    auto obs = worldObservations(event);
    check(obs.size() == 1 && obs[0].x == 100 && obs[0].y == 20 && obs[0].sensorId == 1,
          "world-space observation changed coordinate frame");
    auto first = fusion.accept(event);
    auto second = fusion.accept(input.scan(0, 2, {{102, 20}}));
    check(second.tracks.size() == 1 && second.tracks[0].sensors.size() == 2, "overlapping sensors split track");
    check(second.tracks[0].x > 100 && second.tracks[0].x < 102, "measurements were not fused");
    check(second.tracks[0].state == "tentative", "simultaneous observations confirmed a track");
    auto third = fusion.accept(input.scan(.25f, 2, {{104, 20}}));
    check(third.tracks[0].state == "confirmed" && third.tracks[0].vx > 0, "asynchronous track did not learn velocity");
    auto fourth = fusion.accept(input.scan(.375f, 1, {{105, 20}}));
    check(fourth.tracks.size() == 1 && fourth.tracks[0].id == first.tracks[0].id, "asynchronous association lost identity");
    fusion.accept(input.event(.375f, RunFinished{})); fusion.finish();
}

void lifecycleAndReset() {
    FusionSystem fusion;
    Input input;
    input.start(fusion);
    fusion.accept(input.scan(0, 1, {{0, 0}, {200, 0}}));
    fusion.accept(input.scan(.25f, 2, {{1, 0}}));
    auto coast = fusion.accept(input.scan(1, 1, {}));
    check(coast.tracks.size() == 1 && coast.tracks[0].state == "coasting" && coast.retired.size() == 1,
          "coasting/tentative expiration incorrect");
    auto expired = fusion.accept(input.scan(2.25f, 2, {}));
    check(expired.tracks.empty() && expired.retired[0].reason == "timeout", "empty scans did not expire track");
    auto revived = fusion.accept(input.scan(2.5f, 1, {{0, 0}}));
    check(revived.tracks[0].id == 3, "expired ID reused");
    input.sensorGenerations[0] = 1; input.scans[0] = 0; input.detections[0] = 1;
    fusion.accept(input.event(2.5f, SensorReset{1, 1}));
    auto sensorReset = fusion.accept(input.scan(2.5f, 1, {{0, 0}}));
    check(sensorReset.tracks[0].id == 3 && sensorReset.associations[0].observation.sensorGeneration == 1,
          "sensor reset destroyed global identity");
    ++input.generation;
    auto reset = fusion.accept(input.event(0, RunReset{}));
    check(reset.tracks.empty() && reset.retired[0].trackId == 3, "run reset retained tracks");
    input.scans[0] = input.sensorGenerations[0] = 0; input.detections[0] = 1;
    fusion.accept(input.event(0, SensorStarted{1, 0, 7}));
    auto next = fusion.accept(input.scan(0, 1, {{0, 0}}));
    check(next.tracks[0].id == 4, "global ID reused across run generation");
}

void oneToOneAndTieBreaking() {
    FusionSystem fusion;
    Input input;
    input.start(fusion);
    auto first = fusion.accept(input.scan(0, 1, {{-2, 0}, {2, 0}}));
    check(first.tracks.size() == 2, "same scan observations merged");
    auto tie = fusion.accept(input.scan(0, 2, {{0, 0}, {0, 0}}));
    check(tie.tracks.size() == 2 && tie.associations[0].trackId == 1 && tie.associations[1].trackId == 2,
          "tie is not stable one-to-one matching");
    auto outside = fusion.accept(input.scan(.25f, 1, {{300, 0}}));
    check(outside.associations[0].trackId == 3, "distance gate ignored");
}

void integrityAndReplay() {
    FusionSystem fusion;
    Input input;
    input.start(fusion);
    auto scan = input.scan(0, 1, {{1, 2}});
    auto original = fusion.accept(scan);
    bool rejected = false;
    try { fusion.accept(scan); } catch (const std::exception&) { rejected = true; }
    check(rejected, "duplicate accepted");
    scan = input.scan(.25f, 2, {{2, 3}});
    auto invalid = scan; invalid.identity.timeSeconds = -1;
    rejected = false;
    try { fusion.accept(invalid); } catch (const std::exception&) { rejected = true; }
    check(rejected, "invalid timestamp accepted");
    auto result = fusion.accept(scan);
    check(result.tracks[0].id == original.tracks[0].id, "rejection changed track state");
    std::ostringstream a, b;
    printGlobalTrackEvent(a, result, fusion.config());
    printGlobalTrackEvent(b, result, fusion.config());
    check(a.str() == b.str() && a.str().find("truth") == std::string::npos, "unstable/truth-bearing output");
    rejected = false;
    try { fusion.finish(); } catch (const std::exception&) { rejected = true; }
    check(rejected, "truncated fusion accepted");
    rejected = false;
    try { FusionSystem bad(FusionConfig{.gateDistance = -1}); } catch (const std::exception&) { rejected = true; }
    check(rejected, "invalid configuration accepted");
}
}
int main() {
    try { overlapAndAsynchrony(); lifecycleAndReset(); oneToOneAndTieBreaking(); integrityAndReplay(); }
    catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
