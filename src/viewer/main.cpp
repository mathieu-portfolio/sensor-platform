#include "ViewerState.hpp"
#include "ProceduralRun.hpp"
#include <raylib.h>
#include <algorithm>
#include <charconv>
#include <cmath>
#include <fstream>
#include <iostream>
#include <optional>
#include <string>

using namespace sensor_platform;
using namespace sensor_platform::viewer;
namespace {
constexpr Color background{13, 20, 30, 255}, panel{21, 32, 45, 255};
constexpr Color muted{145, 165, 184, 255}, ink{228, 238, 247, 255};
Color sensorColor(int id) {
    constexpr Color palette[]{{74, 195, 255, 255}, {255, 180, 82, 255}, {198, 138, 255, 255}, {90, 214, 170, 255}};
    return palette[static_cast<unsigned>(id) % 4];
}
Color trackColor(const GlobalTrack& track) {
    return track.state == "confirmed" ? Color{85, 230, 170, 255} :
           track.state == "coasting" ? Color{255, 166, 87, 255} : Color{234, 216, 114, 255};
}
struct View {
    double x{}, y{}, span{300};
    float zoom{1};
    Vector2 pan{};
    double scale() const { return std::min(GetScreenWidth() - 360, GetScreenHeight() - 160) / span * zoom; }
    Vector2 point(double px, double py) const {
        return {static_cast<float>((px-x)*scale() + (GetScreenWidth()-320)*0.5 + pan.x),
                static_cast<float>(-(py-y)*scale() + GetScreenHeight()*0.5 + pan.y)};
    }
};
struct WindowState {
    int width{1200}, height{800};
    Vector2 position{};
    bool maximized{};
    void toggleFullscreen() {
        if (IsWindowFullscreen()) {
            ToggleFullscreen();
            SetWindowSize(width, height);
            SetWindowPosition(static_cast<int>(position.x), static_cast<int>(position.y));
            if (maximized) MaximizeWindow();
        } else {
            maximized = IsWindowMaximized();
            if (maximized) RestoreWindow();
            width = GetScreenWidth();
            height = GetScreenHeight();
            position = GetWindowPosition();
            const int monitor = GetCurrentMonitor();
            SetWindowSize(GetMonitorWidth(monitor), GetMonitorHeight(monitor));
            ToggleFullscreen();
        }
    }
};
void label(const std::string& text, int x, int y, int size = 18, Color color = ink) {
    DrawText(text.c_str(), x, y, size, color);
}
View fit(const std::vector<sensor_sandbox::StreamEvent>& events, const std::vector<SensorGeometry>& layout) {
    double left = 0, right = 1, bottom = 0, top = 1;
    auto include = [&](double x, double y) {
        left = std::min(left,x); right = std::max(right,x);
        bottom = std::min(bottom,y); top = std::max(top,y);
    };
    for (const auto& event : events) for (const auto& d : worldObservations(event)) include(d.x,d.y);
    for (const auto& sensor : layout) {
        include(sensor.x-sensor.range, sensor.y-sensor.range);
        include(sensor.x+sensor.range, sensor.y+sensor.range);
    }
    return {(left+right)/2, (bottom+top)/2, std::max({right-left,top-bottom,20.})*1.15};
}

struct ScenarioControls {
    ProceduralFields fields;
    int focused{-1};
    bool replaceSelection{};
    std::string error;
    Rectangle field(int index) const {
        return {static_cast<float>(GetScreenWidth()-168), 124.0f+28*index, 152, 24};
    }
    Rectangle button() const { return {static_cast<float>(GetScreenWidth()-294), 268, 278, 30}; }
    bool update() {
        bool run = false;
        if (IsMouseButtonPressed(MOUSE_BUTTON_LEFT)) {
            focused = -1;
            for (int i = 0; i < 5; ++i)
                if (CheckCollisionPointRec(GetMousePosition(), field(i))) focused = i;
            replaceSelection = focused >= 0;
            run = CheckCollisionPointRec(GetMousePosition(), button());
        }
        if (focused >= 0) {
            if (IsKeyPressed(KEY_TAB)) {
                focused = (focused + (IsKeyDown(KEY_LEFT_SHIFT) || IsKeyDown(KEY_RIGHT_SHIFT) ? 4 : 1)) % 5;
                replaceSelection = true;
            }
            auto& value = fields.values[focused];
            if ((IsKeyDown(KEY_LEFT_CONTROL) || IsKeyDown(KEY_RIGHT_CONTROL)) && IsKeyPressed(KEY_A))
                replaceSelection = true;
            for (int character = GetCharPressed(); character; character = GetCharPressed()) {
                if (character < '0' || character > '9') continue;
                if (replaceSelection) value.clear();
                replaceSelection = false;
                if (value.size() < 10) value += static_cast<char>(character);
                error.clear();
            }
            if (IsKeyPressed(KEY_BACKSPACE) || IsKeyPressedRepeat(KEY_BACKSPACE)) {
                if (replaceSelection) value.clear();
                else if (!value.empty()) value.pop_back();
                replaceSelection = false;
                error.clear();
            }
            if (IsKeyPressed(KEY_ENTER) || IsKeyPressed(KEY_ESCAPE)) focused = -1;
        } else {
            while (GetCharPressed()) {} // Do not carry playback keystrokes into a field.
        }
        return run;
    }
    void draw() const {
        const int side = GetScreenWidth()-310;
        label("PROCEDURAL SCENARIO", side+16, 96, 17);
        const char* names[]{"Scenario seed", "Layout seed", "Duration (s)", "Targets", "Sensors"};
        for (int i = 0; i < 5; ++i) {
            const auto box = field(i);
            label(names[i], side+16, static_cast<int>(box.y)+5, 14, muted);
            DrawRectangleRec(box, focused == i && replaceSelection ? Color{35, 66, 87, 255} : background);
            DrawRectangleLinesEx(box, 1, focused == i ? Color{74, 195, 255, 255} : muted);
            label(fields.values[i], static_cast<int>(box.x)+7, static_cast<int>(box.y)+5, 15);
            if (focused == i && !replaceSelection && static_cast<int>(GetTime()*2) % 2 == 0)
                label("|", static_cast<int>(box.x)+8+MeasureText(fields.values[i].c_str(),15), static_cast<int>(box.y)+5, 15);
        }
        const auto action = button();
        DrawRectangleRec(action, CheckCollisionPointRec(GetMousePosition(), action) ? Color{49, 130, 158, 255} : Color{33, 96, 122, 255});
        label("Generate / Run", static_cast<int>(action.x)+(278-MeasureText("Generate / Run",18))/2, 274, 18);
        if (error.empty()) {
            label("4-120 s / 1-12 targets / 1-8 sensors", side+16, 307, 12, muted);
            label("Click a value to replace; Tab to move", side+16, 323, 12, muted);
        } else {
            // Fit validation feedback into two compact lines; full details also
            // go to stderr. Existing playback stays intact on a rejected run.
            std::size_t split = std::min<std::size_t>(error.size(), 44);
            while (split && MeasureText(error.substr(0,split).c_str(),12) > 278) --split;
            label(error.substr(0,split), side+16, 307, 12, Color{255,166,87,255});
            label(error.substr(split,44), side+16, 323, 12, Color{255,166,87,255});
        }
    }
};

void draw(const std::optional<Playback>& playback, const std::vector<SensorGeometry>& layout, const View& view,
          bool paused, double speed) {
    static const State empty;
    const auto& state = playback ? playback->state() : empty;
    const int width = GetScreenWidth(), height = GetScreenHeight(), side = width - 310;
    ClearBackground(background);
    BeginScissorMode(0, 80, side, height-126);
    const double grid = std::pow(10., std::ceil(std::log10(view.span / view.zoom / 12)));
    const double cx = view.x - view.pan.x/view.scale(), cy = view.y + view.pan.y/view.scale();
    for (int i = -18; i <= 18; ++i) {
        const auto a = view.point((std::floor(cx/grid)+i)*grid, cy);
        const auto b = view.point(cx, (std::floor(cy/grid)+i)*grid);
        DrawLine(static_cast<int>(a.x), 80, static_cast<int>(a.x), height-46, Color{28, 42, 56, 255});
        DrawLine(0, static_cast<int>(b.y), side, static_cast<int>(b.y), Color{28, 42, 56, 255});
    }
    for (const auto& sensor : layout) {
        if (sensor.generation != state.source.runGeneration || !state.sensors.contains(sensor.id)) continue;
        const auto center = view.point(sensor.x, sensor.y);
        const float radius = static_cast<float>(sensor.range * view.scale());
        const auto color = sensorColor(sensor.id);
        // Heading is counterclockwise from world +X; screen Y points down.
        const float start = static_cast<float>(-sensor.headingDegrees - sensor.fovDegrees/2);
        const float end = static_cast<float>(-sensor.headingDegrees + sensor.fovDegrees/2);
        DrawCircleSector(center, radius, start, end, 80, Fade(color, .06f));
        DrawCircleSectorLines(center, radius, start, end, 80, Fade(color, .3f));
        const double angle = sensor.headingDegrees * 3.141592653589793 / 180;
        DrawLineEx(center, view.point(sensor.x + sensor.range*.25*std::cos(angle),
                                     sensor.y + sensor.range*.25*std::sin(angle)), 2, color);
        DrawCircleV(center, 5, color);
        label("S" + std::to_string(sensor.id), static_cast<int>(center.x)+9, static_cast<int>(center.y)-18, 16, color);
    }
    for (const auto& [id, sensor] : state.sensors)
        for (const auto& detection : sensor.latest) {
            const auto p = view.point(detection.x, detection.y);
            DrawCircleLinesV(p, 5, sensorColor(id));
            DrawLineEx({p.x-7,p.y}, {p.x+7,p.y}, 1, sensorColor(id));
            DrawLineEx({p.x,p.y-7}, {p.x,p.y+7}, 1, sensorColor(id));
        }
    for (const auto& track : state.snapshot.tracks) {
        const auto color = trackColor(track);
        const auto& history = state.histories.at(track.id);
        for (std::size_t i = 1; i < history.size(); ++i)
            DrawLineEx(view.point(history[i-1].x, history[i-1].y), view.point(history[i].x, history[i].y), 2,
                       Fade(color, .25f + .6f*static_cast<float>(i)/history.size()));
        const auto p = view.point(track.x, track.y);
        DrawRectangleLinesEx({p.x-8,p.y-8,16,16}, 2, color);
        label("T" + std::to_string(track.id), static_cast<int>(p.x)+11, static_cast<int>(p.y)+6, 16, color);
    }
    EndScissorMode();
    DrawRectangle(side, 80, 310, height-80, panel);
    label("SENSOR PLATFORM", 24, 18, 24);
    label("Recording viewer / world Cartesian / truth hidden", 24, 50, 17, muted);
    if (!playback) label("Choose parameters, then Generate / Run", 30, 105, 20, muted);
    const std::string status = !playback ? "READY" : playback->done() ? "COMPLETE" : paused ? "PAUSED" : "PLAYING";
    label(status + "  " + TextFormat("%.2fx", speed), side+16, 352, 20);
    label("Run " + std::to_string(state.source.runId) + " / gen " + std::to_string(state.source.runGeneration), side+16, 381, 15);
    label(TextFormat("Acquisition time  %.3f s", state.source.timeSeconds), side+16, 404, 15, muted);
    label("Events  " + std::to_string(state.events) + " / " + std::to_string(playback ? playback->size() : 0), side+16, 433, 15);
    label("Scans " + std::to_string(state.scans) + " / Measurements " + std::to_string(state.measurements), side+16, 455, 14);
    label("Tracks " + std::to_string(state.snapshot.tracks.size()) + " / Sensors " + std::to_string(state.sensors.size()), side+16, 477, 15);
    int row = 507;
    std::size_t known = 0;
    for (const auto& [id, sensor] : state.sensors) {
        const bool geometry = std::any_of(layout.begin(), layout.end(), [&](const auto& item) {
            return item.generation == state.source.runGeneration && item.id == id;
        });
        known += geometry;
        if (row > height-143) continue;
        label("S" + std::to_string(id) + "  g" + std::to_string(sensor.generation) +
              "  scans " + std::to_string(sensor.scans) + "  hits " + std::to_string(sensor.measurements),
              side+16, row, 14, sensorColor(id));
        row += 24;
    }
    label("Geometry: " + std::to_string(known) + "/" + std::to_string(state.sensors.size()) + " sensors", side+16, height-120, 14, muted);
    label("+ Latest scan   [] Track / history", side+16, height-98, 14, muted);
    label("Green confirmed / amber coast", side+16, height-76, 14, muted);
    label("Yellow tentative", side+16, height-54, 14, muted);
    DrawRectangle(0, height-46, side, 46, background);
    label("SPACE pause   LEFT/RIGHT step   R restart   +/- speed   Wheel zoom   Drag pan   F fit", 20, height-29, 15, muted);
}
}

int main(int argc, char** argv) {
    try {
        if (argc > 1 && std::string(argv[1]) == "--help") {
            std::cout << "Usage: sensor_platform_viewer [recording.events] [--layout sensors.layout]\n"
                         "       [--frames N] [--screenshot image.png]\n"
                         "Without a recording, use the procedural controls and Generate / Run.\n"
                         "Reuses complete recordings, replay validation and default platform fusion.\n";
            return 0;
        }
        std::string recordingPath, layoutPath, screenshot;
        int firstOption = 1;
        if (argc > 1 && std::string(argv[1]).rfind("--", 0) != 0) {
            recordingPath = argv[1];
            firstOption = 2;
        }
        int frameLimit = 0;
        for (int i = firstOption; i < argc; ++i) {
            const std::string option = argv[i];
            if (++i == argc) throw std::invalid_argument("Missing value for " + option);
            const std::string value = argv[i];
            if (option == "--layout") layoutPath = value;
            else if (option == "--screenshot") screenshot = value;
            else if (option == "--frames") {
                const auto parsed = std::from_chars(value.data(), value.data()+value.size(), frameLimit);
                if (parsed.ec != std::errc{} || parsed.ptr != value.data()+value.size() || frameLimit <= 0)
                    throw std::invalid_argument("--frames must be positive");
            } else throw std::invalid_argument("Unknown option: " + option);
        }
        std::optional<Playback> playback;
        std::vector<SensorGeometry> layout;
        std::vector<sensor_sandbox::StreamEvent> events;
        if (!recordingPath.empty()) {
            std::ifstream recording(recordingPath, std::ios::binary);
            if (!recording) throw std::runtime_error("Cannot open recording: " + recordingPath);
            events = readRecording(recording);
        } else if (!layoutPath.empty()) {
            throw std::invalid_argument("--layout requires a recording; generated runs provide their own layout");
        }
        if (!layoutPath.empty()) {
            std::ifstream input(layoutPath);
            if (!input) throw std::runtime_error("Cannot open layout: " + layoutPath);
            layout = readLayout(input);
        }
        View view = events.empty() ? View{} : fit(events, layout);
        if (!events.empty()) playback.emplace(std::move(events));
        ScenarioControls controls;
        SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_MSAA_4X_HINT | FLAG_WINDOW_HIGHDPI);
        InitWindow(1200, 800, "Sensor Platform | Event-driven recording viewer");
        if (!IsWindowReady()) throw std::runtime_error("Cannot initialize viewer window");
        SetWindowMinSize(1000, 700);
        SetExitKey(KEY_NULL); // Handle fullscreen and field focus before closing.
        SetTargetFPS(60);
        WindowState window;
        bool paused = false;
        double speed = 1.;
        double lastTick = GetTime();
        int frames = 0;
        while (!WindowShouldClose()) {
            const double now = GetTime();
            double elapsed = now - lastTick;
            lastTick = now;
            const bool leaveFullscreen = IsKeyPressed(KEY_ESCAPE) && IsWindowFullscreen();
            if (leaveFullscreen || IsKeyPressed(KEY_F11)) {
                window.toggleFullscreen();
                lastTick = GetTime();
                elapsed = 0;
            }
            const bool wasEditing = controls.focused >= 0;
            bool regenerated = false;
            if (controls.update()) {
                try {
                    const auto config = controls.fields.config();
                    auto prepared = prepareProceduralRecording(config);
                    auto nextView = fit(prepared.events, prepared.layout);
                    Playback nextPlayback(std::move(prepared.events));
                    nextPlayback.advance(0);
                    playback = std::move(nextPlayback);
                    layout = std::move(prepared.layout);
                    view = nextView;
                    paused = false;
                    speed = 1;
                    regenerated = true;
                    controls.error.clear();
                    std::cout << "Generated procedural recording: scenario seed=" << config.scenarioSeed
                              << ", layout seed=" << config.layoutSeed << ", duration=" << config.durationSeconds
                              << ", targets=" << config.targetCount << ", sensors=" << config.sensorCount
                              << ", events=" << playback->size() << std::endl;
                } catch (const std::exception& error) {
                    controls.error = error.what();
                    std::cerr << "Generate / Run: " << error.what() << '\n';
                }
                // Preparation is synchronous; never charge its duration to playback.
                lastTick = GetTime();
                elapsed = 0;
            }
            if (!wasEditing && controls.focused < 0 && !regenerated) {
                if (IsKeyPressed(KEY_ESCAPE) && !leaveFullscreen) break;
                if (IsKeyPressed(KEY_SPACE)) paused = !paused;
                if (playback && IsKeyPressed(KEY_R)) playback->restart();
                if (playback && IsKeyPressed(KEY_RIGHT)) { paused = true; playback->step(); }
                if (playback && IsKeyPressed(KEY_LEFT)) { paused = true; playback->stepBackward(); }
                if (IsKeyPressed(KEY_EQUAL) || IsKeyPressed(KEY_KP_ADD)) speed = std::min(16.,speed*2);
                if (IsKeyPressed(KEY_MINUS) || IsKeyPressed(KEY_KP_SUBTRACT)) speed = std::max(.0625,speed/2);
                if (IsKeyPressed(KEY_F)) { view.pan = {}; view.zoom = 1; }
            }
            if (!regenerated && GetMouseX() < GetScreenWidth()-310) {
                view.zoom = std::clamp(view.zoom*std::pow(1.15f,GetMouseWheelMove()), .1f,20.f);
                if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
                    const auto delta = GetMouseDelta(); view.pan.x += delta.x; view.pan.y += delta.y;
                }
            }
            if (playback && !paused) playback->advance(elapsed*speed);
            BeginDrawing();
            draw(playback,layout,view,paused,speed);
            controls.draw();
            EndDrawing();
            if (frameLimit && ++frames >= frameLimit) break;
        }
        if (!screenshot.empty()) {
            Image capture = LoadImageFromScreen();
            const bool saved = ExportImage(capture, screenshot.c_str());
            UnloadImage(capture);
            if (!saved) { CloseWindow(); throw std::runtime_error("Cannot save screenshot: " + screenshot); }
        }
        std::cout << "Viewer rendered " << (playback ? playback->state().events : 0) << "/" << (playback ? playback->size() : 0)
                  << " events; active tracks=" << (playback ? playback->state().snapshot.tracks.size() : 0) << '\n';
        CloseWindow();
    } catch (const std::exception& error) {
        std::cerr << "viewer: " << error.what() << '\n';
        return 1;
    }
}
