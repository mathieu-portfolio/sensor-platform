#include "viewer/ViewerState.hpp"
#include "viewer/ProceduralRun.hpp"
#include <iostream>
#include <sstream>
#include <stdexcept>

using namespace sensor_platform;
using namespace sensor_platform::viewer;
using namespace sensor_sandbox;
namespace {
void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
template<class F> void rejects(F action) {
    try { action(); } catch (const std::exception&) { return; }
    throw std::runtime_error("Expected rejection");
}
std::vector<StreamEvent> fixture() {
    std::istringstream input(
        "SENSOR_EVENTS 1\nRUN_STARTED 42 0 1 0\nSENSOR_STARTED 42 0 2 0 1 0 7\n"
        "MEASUREMENTS 42 0 3 0 1 0 1 1 1 100 20 .9 2\n"
        "MEASUREMENTS 42 0 4 .5 1 0 2 1 2 101 20 .9 2\n"
        "MEASUREMENTS 42 0 5 .75 1 0 3 0\n"
        "SENSOR_RESET 42 0 6 .75 1 1\n"
        "RUN_RESET 42 1 7 0\nSENSOR_STARTED 42 1 8 0 1 0 7\n"
        "MEASUREMENTS 42 1 9 0 1 0 1 1 1 10 20 .9 2\n"
        "RUN_FINISHED 42 1 10 .5\n");
    return readRecording(input);
}
void stateAndFusion() {
    const auto events = fixture();
    State state;
    FusionSystem reference;
    for (std::size_t i = 0; i < 4; ++i) {
        state.accept(events[i]);
        const auto output = reference.accept(events[i]);
        check(state.snapshot.tracks.size() == output.tracks.size(), "Fusion snapshot size mismatch");
        if (!output.tracks.empty()) {
            check(state.snapshot.tracks[0].x == output.tracks[0].x &&
                  state.snapshot.tracks[0].id == output.tracks[0].id, "Fusion results changed");
        }
    }
    check(state.scans == 2 && state.measurements == 2 && state.events == 4, "Counters incorrect");
    check(state.snapshot.tracks[0].state == "confirmed", "Track not confirmed");
    check(state.histories.at(1).size() == 2, "History missing");
    rejects([&] { state.accept(events[3]); });
    check(state.events == 4 && state.histories.at(1).size() == 2, "Rejected event mutated viewer");
    state.accept(events[4]);
    check(state.sensors.at(1).latest.empty() && state.scans == 3, "Empty scan retained old detections");
    state.accept(events[5]);
    check(state.sensors.at(1).generation == 1 && state.sensors.at(1).scans == 0, "Sensor reset failed");
    check(!state.histories.empty(), "Sensor reset erased global tracks");
    state.accept(events[6]);
    check(state.sensors.empty() && state.histories.empty() && state.snapshot.tracks.empty(), "Run reset leaked state");
    for (std::size_t i = 7; i < events.size(); ++i) state.accept(events[i]);
    check(state.finished && state.events == 10 && state.scans == 4 && state.measurements == 3, "Finish counters wrong");
    check(state.snapshot.tracks[0].id == 2, "Track identity reused across reset");
}
void playbackTiming() {
    Playback playback(fixture());
    playback.advance(0);
    check(playback.state().events == 3, "Simultaneous events not delivered together");
    playback.advance(.25);
    check(playback.state().events == 3, "Playback invented event");
    playback.step();
    check(playback.state().events == 4, "Single-event step failed");
    playback.advance(.25);
    check(playback.state().events == 9 && playback.state().source.runGeneration == 1, "Reset timeline incorrect");
    playback.advance(.5);
    check(playback.done() && playback.state().finished, "Playback did not finish");
    playback.advance(100);
    check(playback.state().events == 10, "Finished playback advanced processing");
    playback.restart();
    check(playback.state().events == 0 && playback.state().histories.empty(), "Restart retained state");
    rejects([&] { playback.advance(-1); });
    auto broken = fixture(); broken.pop_back();
    rejects([&] { Playback invalid(broken); });
}
void boundedHistoryAndRetirement() {
    State state;
    state.accept({{1,0,1,0},RunStarted{}});
    state.accept({{1,0,2,0},SensorStarted{1,0,7}});
    for (int i = 0; i < 80; ++i)
        state.accept({{1,0,static_cast<std::uint64_t>(i+3),i*.1f},
                      RadarMeasurements{1,0,static_cast<std::uint64_t>(i+1),{{i+1,1,{i*.1f,0},.9f,2}}}});
    check(state.histories.at(1).size() == State::historyLimit, "History not bounded");
    state.accept({{1,0,83,11},RunFinished{}});
    check(state.histories.empty() && state.snapshot.tracks.empty(), "Retired history leaked");
}
void backwardPlayback() {
    const auto events = fixture();
    Playback playback(events);
    playback.advance(100);
    for (std::size_t count = events.size(); count > 0; --count) {
        playback.stepBackward();
        Playback reference(events);
        for (std::size_t i = 0; i < count - 1; ++i) reference.step();
        const auto& actual = playback.state();
        const auto& expected = reference.state();
        std::ostringstream a, b;
        printGlobalTrackEvent(a, actual.snapshot, {});
        printGlobalTrackEvent(b, expected.snapshot, {});
        check(a.str() == b.str(), "Backward fusion snapshot differs from fresh replay");
        check(actual.events == expected.events && actual.scans == expected.scans &&
              actual.measurements == expected.measurements && actual.finished == expected.finished,
              "Backward counters/finish differ");
        check(actual.sensors.size() == expected.sensors.size() && actual.histories.size() == expected.histories.size(),
              "Backward reset state differs");
        for (const auto& [id, sensor] : expected.sensors) {
            const auto& got = actual.sensors.at(id);
            check(got.generation == sensor.generation && got.scans == sensor.scans &&
                  got.measurements == sensor.measurements && got.latest.size() == sensor.latest.size(),
                  "Backward sensor state differs");
            for (std::size_t i = 0; i < sensor.latest.size(); ++i)
                check(got.latest[i].x == sensor.latest[i].x && got.latest[i].y == sensor.latest[i].y,
                      "Backward observation differs");
        }
        for (const auto& [id, history] : expected.histories) {
            const auto& got = actual.histories.at(id);
            check(got.size() == history.size(), "Backward history size differs");
            for (std::size_t i = 0; i < history.size(); ++i)
                check(got[i].x == history[i].x && got[i].y == history[i].y, "Backward history differs");
        }
        check(!playback.done(), "Backward from completion remained complete");
        playback.step();
        check(playback.state().events == count, "Forward after backward failed");
        playback.stepBackward();
    }
    playback.stepBackward();
    check(playback.state().events == 0, "Backward at start underflowed");
    playback.advance(.5);
    playback.stepBackward(); // Restore time zero, not the former wall clock.
    playback.advance(.25);
    check(playback.state().events == 3, "Backward retained stale playback clock");
    playback.advance(.25);
    check(playback.state().events == 4, "Timed resume after backward failed");
    playback.advance(100);
    check(playback.done() && playback.state().finished, "Resume did not complete");
}
void layoutValidation() {
    std::istringstream good("SENSOR_LAYOUT 1\n# gen id x y heading fov range\n0 1 50 20 90 60 150\n1 1 0 0 0 360 200\n");
    const auto layout = readLayout(good);
    check(layout.size() == 2 && layout[0].headingDegrees == 90 && layout[1].generation == 1, "Layout decoding failed");
    for (const auto* bad : {"SENSOR_LAYOUT 2\n", "SENSOR_LAYOUT 1\n0 1 0 0 0 361 2\n",
                            "SENSOR_LAYOUT 1\n0 1 0 0 0 60 -2\n", "SENSOR_LAYOUT 1\n0 1 nan 0 0 60 2\n",
                            "SENSOR_LAYOUT 1\n0 1 0 0 0 60 2\n0 1 1 0 0 60 2\n"})
        rejects([&] { std::istringstream input(bad); readLayout(input); });
}
std::string recordingBytes(const std::vector<StreamEvent>& events) {
    std::ostringstream output;
    writeRecording(output, events);
    return output.str();
}
std::string geometryBytes(const std::vector<SensorGeometry>& layout) {
    std::ostringstream output;
    output.precision(17);
    for (const auto& sensor : layout)
        output << sensor.id << ' ' << sensor.x << ' ' << sensor.y << ' ' << sensor.range << '\n';
    return output.str();
}
void proceduralControlsAndRun() {
    ProceduralFields fields;
    const auto defaults = fields.config();
    check(defaults.scenarioSeed == 2026 && defaults.layoutSeed == 73 && defaults.durationSeconds == 20 &&
          defaults.targetCount == 4 && defaults.sensorCount == 3, "UI defaults differ from curated demo");
    const auto first = prepareProceduralRecording(defaults);
    const auto repeated = prepareProceduralRecording(fields.config());
    const auto bytes = recordingBytes(first.events);
    check(bytes == recordingBytes(repeated.events), "UI repeated run is not deterministic");
    // Compare the adapter against the existing runtime's producer and recorder.
    std::ostringstream direct;
    IncrementalRecording writer(direct);
    runProcedural(43, generateScenario(defaults), [&](const auto& event) { writer.append(event); });
    writer.finish();
    check(bytes == direct.str(), "UI bypassed or changed the procedural recording path");
    check(first.events.size() == 148 && first.layout.size() == 3, "Default UI run did not launch");
    Playback playback(first.events);
    playback.advance(20);
    check(playback.done() && playback.state().scans == 143 && playback.state().measurements > 400,
          "Generated recording did not reach existing playback/fusion");
    playback.stepBackward();
    check(!playback.done(), "Generated playback cannot step back after completion");
    playback.restart();
    check(playback.state().events == 0 && playback.state().histories.empty(), "Generated restart leaked tracks");
    fields.values[0] = "2027";
    const auto targetChanged = prepareProceduralRecording(fields.config());
    check(bytes != recordingBytes(targetChanged.events), "Changing UI scenario seed did not change recording");
    check(geometryBytes(first.layout) == geometryBytes(targetChanged.layout), "UI scenario seed changed locked layout");
    fields = {};
    fields.values[1] = "74";
    const auto layoutChanged = prepareProceduralRecording(fields.config());
    check(geometryBytes(first.layout) != geometryBytes(layoutChanged.layout), "Changing UI layout seed did not change geometry");
    fields.values = {"0", "4294967295", "4", "5", "4"};
    const auto custom = prepareProceduralRecording(fields.config());
    check(custom.layout.size() == 4 && custom.events.back().identity.timeSeconds == 4,
          "UI duration/counts were not forwarded");
    fields.parameters = {"8", "12", "0", "0", "1.5", "1.6", "3", "0", "0.9", "0"};
    const auto retained = fields.parameters;
    const auto extended = fields.config();
    check(extended.speedMin == 8 && extended.speedMax == 12 && extended.maneuver == 0 &&
          extended.convergence == 0 && extended.spawnSpread == 1.5f && extended.coverage == 1.6f &&
          extended.layoutSpread == 3 && extended.noise == 0 && extended.reliability == .9f && extended.clutter == 0,
          "UI parameter mapping differs from runtime");
    const auto contrasted = prepareProceduralRecording(extended);
    check(recordingBytes(custom.events) != recordingBytes(contrasted.events) &&
          geometryBytes(custom.layout) != geometryBytes(contrasted.layout), "UI parameters did not reach generator");
    check(recordingBytes(contrasted.events) == recordingBytes(prepareProceduralRecording(fields.config()).events) &&
          fields.parameters == retained, "UI generation changed configuration or determinism");
    for (const auto& invalid : {"", "nan", "inf", "1.2.3", "1 2", "-1", "31"}) {
        fields.parameters[0] = invalid;
        rejects([&] { fields.config(); });
    }
    for (const auto& invalid : std::vector<std::pair<int,std::string>>{
             {0,""}, {0,"-1"}, {0,"4294967296"}, {0,"1 2"}, {1,"1.5"},
             {2,"3"}, {2,"121"}, {3,"0"}, {3,"13"}, {4,"0"}, {4,"9"}}) {
        fields = {};
        fields.values[invalid.first] = invalid.second;
        rejects([&] { fields.config(); });
    }
}
void regenerationPreservesSpeed() {
    ProceduralConfig config;
    config.durationSeconds = 4;
    const auto generated = prepareProceduralRecording(config);
    Playback fresh(generated.events);
    fresh.advance(0);
    for (const double speed : {.25, 4.}) {
        PlaybackSession session;
        session.playback.emplace(fixture());
        session.playback->advance(100);
        check(session.playback->done() && !session.playback->state().histories.empty(), "Missing old run state");
        session.speed = speed;
        session.paused = true;
        session.replaceRecording(generated.events);
        check(session.speed == speed && !session.paused, "Regeneration changed speed or failed to resume");
        const auto& actual = session.playback->state();
        const auto& expected = fresh.state();
        check(actual.source.timeSeconds == 0 && !session.playback->done() && !actual.finished,
              "Regeneration retained old playback position");
        check(actual.events == expected.events && actual.scans == expected.scans &&
              actual.measurements == expected.measurements && actual.sensors.size() == expected.sensors.size(),
              "Regeneration retained old counters/sensors");
        std::ostringstream a, b;
        printGlobalTrackEvent(a, actual.snapshot, {});
        printGlobalTrackEvent(b, expected.snapshot, {});
        check(a.str() == b.str() && actual.histories.size() == expected.histories.size(), "Regeneration retained old tracks");
        for (const auto& [id, history] : expected.histories)
            check(actual.histories.at(id).size() == history.size(), "Regeneration retained old history");
        Playback timedReference(generated.events);
        timedReference.advance(.125 * speed);
        session.playback->advance(.125 * session.speed);
        check(session.playback->state().events == timedReference.state().events,
              "Regeneration retained old playback clock");
    }
}
}
int main() {
    try { stateAndFusion(); playbackTiming(); backwardPlayback(); boundedHistoryAndRetirement(); layoutValidation(); proceduralControlsAndRun(); regenerationPreservesSpeed(); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
    std::cout << "Viewer state, replay, fusion, layout and procedural controls checks passed\n";
}
