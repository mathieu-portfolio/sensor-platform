#include "RunSession.hpp"
#include "EventRecording.hpp"

#include <algorithm>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>

using namespace sensor_sandbox;
using namespace sensor_platform;

namespace {
void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }

std::string encode(const std::vector<StreamEvent>& events) {
    std::ostringstream output;
    writeRecording(output, events);
    return output.str();
}

std::vector<StreamEvent> decode(const std::string& text) {
    std::istringstream input(text);
    return readRecording(input);
}

void append(std::vector<StreamEvent>& events, std::vector<StreamEvent> batch) {
    events.insert(events.end(), batch.begin(), batch.end());
}

std::vector<SensorConfig> configs() {
    return {
        {.id = 2, .position = {20, 0},
         .definition = {.range = 200, .refreshRateHz = 4, .rangeNoise = 7,
                        .detectionProbability = 0.5f, .falsePositiveRateHz = 4}, .seed = 73},
        {.id = 1, .position = {0, 0},
         .definition = {.range = 1, .refreshRateHz = 2}, .seed = 42}
    };
}

std::vector<Entity> entities() {
    Entity entity;
    entity.id = 7;
    entity.position = {100, 0};
    entity.velocity = {10, 0};
    return {entity};
}

std::vector<StreamEvent> run(bool reverse = false) {
    auto configuration = configs();
    if (reverse) std::reverse(configuration.begin(), configuration.end());
    RunSession session(123, entities(), configuration);
    auto events = session.start();
    append(events, session.advanceTo(0));
    append(events, session.advanceTo(0.25f));
    events.push_back(session.resetSensor(2));
    append(events, session.advanceTo(0.25f));
    append(events, session.advanceTo(0.5f));
    append(events, session.resetRun());
    append(events, session.advanceTo(0));
    append(events, session.advanceTo(0.5f));
    events.push_back(session.finish());
    return events;
}

void sameEvents(const std::vector<StreamEvent>& a, const std::vector<StreamEvent>& b) {
    check(a.size() == b.size(), "event count differs");
    for (std::size_t i = 0; i < a.size(); ++i) {
        const auto& x = a[i];
        const auto& y = b[i];
        check(x.identity.runId == y.identity.runId &&
              x.identity.runGeneration == y.identity.runGeneration &&
              x.identity.streamSequence == y.identity.streamSequence &&
              x.identity.timeSeconds == y.identity.timeSeconds, "event metadata differs");
        check(x.payload.index() == y.payload.index(), "event type differs");
        std::visit([&](const auto& p) {
            using T = std::decay_t<decltype(p)>;
            const auto& q = std::get<T>(y.payload);
            if constexpr (std::is_same_v<T, SensorStarted> || std::is_same_v<T, SensorReset> ||
                          std::is_same_v<T, RadarMeasurements>) {
                check(p.sensorId == q.sensorId && p.sensorGeneration == q.sensorGeneration,
                      "sensor identity differs");
            }
            if constexpr (std::is_same_v<T, SensorStarted>) check(p.seed == q.seed, "seed differs");
            if constexpr (std::is_same_v<T, RadarMeasurements>) {
                check(p.scanSequence == q.scanSequence && p.detections.size() == q.detections.size(),
                      "scan differs");
                for (std::size_t j = 0; j < p.detections.size(); ++j) {
                    const auto& d = p.detections[j];
                    const auto& e = q.detections[j];
                    check(d.id == e.id && d.sensorId == e.sensorId &&
                          d.estimatedPosition.x == e.estimatedPosition.x &&
                          d.estimatedPosition.y == e.estimatedPosition.y &&
                          d.confidence == e.confidence && d.uncertaintyRadius == e.uncertaintyRadius,
                          "measurement does not round trip exactly");
                }
            }
        }, x.payload);
    }
}

// A small downstream consumer used unchanged for live and decoded events.
std::map<SensorId, std::pair<std::size_t, std::size_t>> totals(const std::vector<StreamEvent>& events) {
    std::map<SensorId, std::pair<std::size_t, std::size_t>> result;
    for (const auto& event : events) {
        if (const auto* scan = std::get_if<RadarMeasurements>(&event.payload)) {
            ++result[scan->sensorId].first;
            result[scan->sensorId].second += scan->detections.size();
        }
    }
    return result;
}

void orderingIdentityAndReplay() {
    const auto live = run();
    sameEvents(live, run(true));
    sameEvents(live, run());
    const auto recording = encode(live);
    const auto replay = decode(recording);
    sameEvents(live, replay);
    check(recording == encode(replay), "observable event sequence changed");
    check(totals(live) == totals(replay), "downstream state changed");

    bool empty = false, sensorReset = false, runReset = false;
    std::map<SensorId, std::uint64_t> expectedScan;
    for (std::size_t i = 0; i < live.size(); ++i) {
        const auto& e = live[i];
        check(e.identity.streamSequence == i + 1, "stream sequence not contiguous");
        if (const auto* s = std::get_if<SensorStarted>(&e.payload)) expectedScan[s->sensorId] = 0;
        if (const auto* s = std::get_if<SensorReset>(&e.payload)) {
            sensorReset = true;
            check(s->sensorId == 2 && s->sensorGeneration == 1 && e.identity.timeSeconds == 0.25f,
                  "wrong sensor reset identity");
            expectedScan[2] = 0;
            const auto& next = std::get<RadarMeasurements>(live[i + 1].payload);
            check(next.sensorId == 2 && next.sensorGeneration == 1 && next.scanSequence == 1,
                  "sensor reset did not restart only its stream");
        }
        if (std::holds_alternative<RunReset>(e.payload)) {
            runReset = true;
            check(e.identity.runId == 123 && e.identity.runGeneration == 1 && e.identity.timeSeconds == 0,
                  "wrong run reset identity");
        }
        if (const auto* scan = std::get_if<RadarMeasurements>(&e.payload)) {
            check(scan->scanSequence == ++expectedScan[scan->sensorId], "scan sequence not local/contiguous");
            if (scan->sensorId == 1) {
                check(scan->detections.empty() && scan->sensorGeneration == 0, "empty scan or reset isolation lost");
                empty = true;
            }
        }
    }
    check(empty && sensorReset && runReset, "fixture missed required event kinds");
}

template<class F> void rejects(F action) {
    try { action(); } catch (const std::exception&) { return; }
    throw std::runtime_error("malformed recording or invalid lifecycle was accepted");
}

void malformedAndTruncated() {
    const auto events = run();
    const auto good = encode(events);
    // Every proper line-boundary prefix is incomplete, including a missing final marker.
    for (std::size_t end = good.find('\n'); end + 1 < good.size(); end = good.find('\n', end + 1)) {
        rejects([&] { decode(good.substr(0, end + 1)); });
    }
    rejects([&] { decode(good.substr(0, good.size() - 5)); });
    rejects([&] { decode(good + "garbage\n"); });
    auto badVersion = good;
    badVersion.replace(0, 15, "SENSOR_EVENTS 2");
    rejects([&] { decode(badVersion); });
    rejects([&] { decode("SENSOR_EVENTS 1\nRUN_STARTED -1 0 1 0\nRUN_FINISHED -1 0 2 0\n"); });
    rejects([&] { decode("SENSOR_EVENTS 1\nRUN_STARTED 1 0 1 0 extra\n"); });
    rejects([&] { decode("SENSOR_EVENTS 1\nUNKNOWN 1 0 1 0\n"); });
    rejects([&] { decode("SENSOR_EVENTS 1\nRUN_STARTED 1 0 1 0\nMEASUREMENTS 1 0 2 0 1 0 1 1 1 0\n"); });

    for (int fault = 0; fault < 5; ++fault) {
        auto bad = events;
        if (fault == 0) bad[1].identity.streamSequence = 9;
        if (fault == 1) bad[1].identity.runId = 456;
        if (fault == 2) bad[1].identity.timeSeconds = std::numeric_limits<float>::quiet_NaN();
        if (fault == 3) std::get<SensorStarted>(bad[1].payload).sensorGeneration = 7;
        if (fault == 4) {
            auto& scan = std::get<RadarMeasurements>(bad[3].payload);
            scan.scanSequence = 3;
        }
        // Bypass writeRecording's validation to test replay's independent validation.
        std::ostringstream text;
        text << "SENSOR_EVENTS 1\n";
        for (const auto& e : bad) printEvent(text, e);
        rejects([&] { decode(text.str()); });
    }
}

void lifecycleAndPrecision() {
    RunSession session(99, entities(), configs());
    rejects([&] { session.advanceTo(0); });
    auto events = session.start();
    rejects([&] { session.start(); });
    rejects([&] { session.resetSensor(999); });
    append(events, session.advanceTo(0));
    events.push_back(session.finish());
    rejects([&] { session.resetRun(); });
    rejects([&] { session.advanceTo(1); });
    // Exercise values that two-decimal display would destroy.
    auto& scan = std::get<RadarMeasurements>(events[4].payload);
    scan.detections[0].estimatedPosition = {0.123456789f, -12345.6789f};
    scan.detections[0].confidence = 0.123456789f;
    scan.detections[0].uncertaintyRadius = 0.00000123456789f;
    sameEvents(events, decode(encode(events)));
}
}

int main() {
    try {
        orderingIdentityAndReplay();
        malformedAndTruncated();
        lifecycleAndPrecision();
        std::cout << "Event recording/replay tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
