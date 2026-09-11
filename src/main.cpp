#include <charconv>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <iostream>

#include "EventTransport.hpp"
#include "EventRecording.hpp"

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
        sensor_platform::IncrementalRecording live(std::cout);
        if (!recordPath.empty()) {
            std::ofstream output(recordPath, std::ios::binary | std::ios::trunc);
            if (!output) throw std::runtime_error("Cannot create recording: " + recordPath);
            sensor_platform::IncrementalRecording recording(output);
            sensor_platform::runSample(runId, [&](const auto& event) {
                recording.append(event);
                live.append(event);
            });
            recording.finish();
            output.close();
            if (!output) throw std::runtime_error("Failed to close recording: " + recordPath);
        } else {
            sensor_platform::runSample(runId, [&](const auto& event) { live.append(event); });
        }
        live.finish();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}