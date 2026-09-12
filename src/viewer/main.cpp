#include "ViewerState.hpp"
#include <raylib.h>
#include <algorithm>
#include <charconv>
#include <cmath>
#include <fstream>
#include <iostream>
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
void label(const std::string& text, int x, int y, int size = 18, Color color = ink) {
    DrawText(text.c_str(), x, y, size, color);
}
void draw(const Playback& playback, const std::vector<SensorGeometry>& layout, const View& view,
          bool paused, double speed) {
    const auto& state = playback.state();
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
    const std::string status = playback.done() ? "COMPLETE" : paused ? "PAUSED" : "PLAYING";
    label(status + "  " + TextFormat("%.2fx", speed), side+20, 100, 22);
    label("Run " + std::to_string(state.source.runId) + " / gen " + std::to_string(state.source.runGeneration), side+20, 140);
    label(TextFormat("Acquisition time  %.3f s", state.source.timeSeconds), side+20, 168, 17, muted);
    label("Events  " + std::to_string(state.events) + " / " + std::to_string(playback.size()), side+20, 211);
    label("Scans  " + std::to_string(state.scans), side+20, 239);
    label("Measurements  " + std::to_string(state.measurements), side+20, 267);
    label("Active tracks  " + std::to_string(state.snapshot.tracks.size()), side+20, 295);
    label("Sensors  " + std::to_string(state.sensors.size()), side+20, 335);
    int row = 365;
    std::size_t known = 0;
    for (const auto& [id, sensor] : state.sensors) {
        const bool geometry = std::any_of(layout.begin(), layout.end(), [&](const auto& item) {
            return item.generation == state.source.runGeneration && item.id == id;
        });
        known += geometry;
        if (row > height-205) continue;
        label("S" + std::to_string(id) + "  g" + std::to_string(sensor.generation) +
              "  scans " + std::to_string(sensor.scans) + "  hits " + std::to_string(sensor.measurements),
              side+20, row, 15, sensorColor(id));
        row += 24;
    }
    label("Geometry: " + std::to_string(known) + "/" + std::to_string(state.sensors.size()) + " sensors", side+20, height-184, 16, muted);
    label(layout.empty() ? "Geometry unavailable" : "Layout supplied separately", side+20, height-160, 16, muted);
    label("+ Latest scan per sensor", side+20, height-126, 16, muted);
    label("[] Tracks / short histories", side+20, height-102, 16, muted);
    label("Green confirmed / amber coast", side+20, height-78, 15, muted);
    label("Yellow tentative", side+20, height-55, 15, muted);
    DrawRectangle(0, height-46, side, 46, background);
    label("SPACE pause   LEFT/RIGHT step   R restart   +/- speed   Wheel zoom   Drag pan   F fit", 20, height-29, 15, muted);
}
}

int main(int argc, char** argv) {
    try {
        if (argc < 2 || std::string(argv[1]) == "--help") {
            std::cout << "Usage: sensor_platform_viewer <recording.events> [--layout sensors.layout]\n"
                         "       [--frames N] [--screenshot image.png]\n"
                         "Complete recording only. Reuses replay validation and default platform fusion.\n";
            return argc < 2 ? 1 : 0;
        }
        std::string layoutPath, screenshot;
        int frameLimit = 0;
        for (int i = 2; i < argc; ++i) {
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
        std::ifstream recording(argv[1], std::ios::binary);
        if (!recording) throw std::runtime_error("Cannot open recording: " + std::string(argv[1]));
        auto events = readRecording(recording);
        std::vector<SensorGeometry> layout;
        if (!layoutPath.empty()) {
            std::ifstream input(layoutPath);
            if (!input) throw std::runtime_error("Cannot open layout: " + layoutPath);
            layout = readLayout(input);
        }
        // Stable fit from recorded observations and explicitly supplied geometry.
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
        View view{(left+right)/2, (bottom+top)/2, std::max({right-left,top-bottom,20.})*1.15};
        Playback playback(std::move(events));
        SetConfigFlags(FLAG_WINDOW_RESIZABLE | FLAG_MSAA_4X_HINT | FLAG_WINDOW_HIGHDPI);
        InitWindow(1200, 800, "Sensor Platform | Event-driven recording viewer");
        if (!IsWindowReady()) throw std::runtime_error("Cannot initialize viewer window");
        SetWindowMinSize(1000, 700);
        SetTargetFPS(60);
        bool paused = false;
        double speed = 1.;
        int frames = 0;
        while (!WindowShouldClose()) {
            if (IsKeyPressed(KEY_SPACE)) paused = !paused;
            if (IsKeyPressed(KEY_R)) playback.restart();
            if (IsKeyPressed(KEY_RIGHT)) { paused = true; playback.step(); }
            if (IsKeyPressed(KEY_LEFT)) { paused = true; playback.stepBackward(); }
            if (IsKeyPressed(KEY_EQUAL) || IsKeyPressed(KEY_KP_ADD)) speed = std::min(16.,speed*2);
            if (IsKeyPressed(KEY_MINUS) || IsKeyPressed(KEY_KP_SUBTRACT)) speed = std::max(.0625,speed/2);
            if (IsKeyPressed(KEY_F)) { view.pan = {}; view.zoom = 1; }
            if (GetMouseX() < GetScreenWidth()-310) {
                view.zoom = std::clamp(view.zoom*std::pow(1.15f,GetMouseWheelMove()), .1f,20.f);
                if (IsMouseButtonDown(MOUSE_BUTTON_LEFT)) {
                    const auto delta = GetMouseDelta(); view.pan.x += delta.x; view.pan.y += delta.y;
                }
            }
            if (!paused) playback.advance(GetFrameTime()*speed);
            BeginDrawing();
            draw(playback,layout,view,paused,speed);
            EndDrawing();
            if (frameLimit && ++frames >= frameLimit) break;
        }
        if (!screenshot.empty()) {
            Image capture = LoadImageFromScreen();
            const bool saved = ExportImage(capture, screenshot.c_str());
            UnloadImage(capture);
            if (!saved) { CloseWindow(); throw std::runtime_error("Cannot save screenshot: " + screenshot); }
        }
        std::cout << "Viewer rendered " << playback.state().events << "/" << playback.size()
                  << " events; active tracks=" << playback.state().snapshot.tracks.size() << '\n';
        CloseWindow();
    } catch (const std::exception& error) {
        std::cerr << "viewer: " << error.what() << '\n';
        return 1;
    }
}
