#include <charconv>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <iostream>

#include "RunSession.hpp"
#include "EventRecording.hpp"

std::vector<sensor_sandbox::StreamEvent> sampleRun(sensor_sandbox::RunId runId) {
    using namespace sensor_sandbox;
    using sensor_platform::SensorConfig;

    Entity entity;
    entity.id = 1;
    entity.label = "Straight transit";
    entity.position = {100.0f, 0.0f};
    entity.velocity = {10.0f, 0.0f};

    // Concrete in-process configuration; each seed belongs to its sensor ID.
    const std::vector<SensorConfig> configs{
        {.id = 1, .position = {0, 0},
         .definition = {.range = 200, .refreshRateHz = 1}, .seed = 11},
        {.id = 2, .position = {50, 20},
         .definition = {.range = 150, .refreshRateHz = 2}, .seed = 22},
        {.id = 3, .position = {150, -20},
         .definition = {.range = 100, .refreshRateHz = 4, .rangeNoise = 2,
                        .detectionProbability = 0.75f, .falsePositiveRateHz = 1}, .seed = 33}
    };
    sensor_platform::RunSession session(runId, {entity}, configs);
    auto events = session.start();
    for (int step = 0; step <= 4; ++step) {
        auto batch = session.advanceTo(static_cast<float>(step) * 0.25f);
        events.insert(events.end(), std::make_move_iterator(batch.begin()), std::make_move_iterator(batch.end()));
    }
    events.push_back(session.finish());
    return events;
}

int main(int argc, char** argv) {
    try {
        const std::string command = argc > 1 ? argv[1] : "run";
        if (command == "replay") {
            if (argc != 3) throw std::invalid_argument("Usage: sensor_platform replay <path>");
            std::ifstream input(argv[2], std::ios::binary);
            if (!input) throw std::runtime_error("Cannot open recording: " + std::string(argv[2]));
            // No simulation on this path. Read/validate the entire run before output.
            const auto events = sensor_platform::readRecording(input);
            sensor_platform::writeRecording(std::cout, events);
            return 0;
        }
        if (command != "run") throw std::invalid_argument("Usage: sensor_platform [run [--record <path>] [--run-id <positive integer>]] | replay <path>");
        sensor_sandbox::RunId runId = 1;
        std::string recordPath;
        bool hasRunId = false;
        for (int i = 2; i < argc; ++i) {
            const std::string option = argv[i];
            if (++i == argc) throw std::invalid_argument("Missing value for " + option);
            const std::string value = argv[i];
            if (option == "--record" && recordPath.empty() && !value.empty()) recordPath = value;
            else if (option == "--run-id" && !hasRunId) {
                const auto parsed = std::from_chars(value.data(), value.data() + value.size(), runId);
                if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || runId == 0)
                    throw std::invalid_argument("Run ID must be a positive integer");
                hasRunId = true;
            } else throw std::invalid_argument("Unknown or duplicate option: " + option);
        }
        const auto events = sampleRun(runId);
        if (!recordPath.empty()) {
            std::ofstream output(recordPath, std::ios::binary | std::ios::trunc);
            if (!output) throw std::runtime_error("Cannot create recording: " + recordPath);
            sensor_platform::writeRecording(output, events);
            output.close();
            if (!output) throw std::runtime_error("Failed to close recording: " + recordPath);
        }
        sensor_platform::writeRecording(std::cout, events);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}