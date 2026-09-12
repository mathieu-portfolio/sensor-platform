#include <charconv>
#include <fstream>
#include <iterator>
#include <optional>
#include <stdexcept>
#include <string>
#include <iostream>

#include "EventTransport.hpp"
#include "EventRecording.hpp"
#include "Experiment.hpp"
#include "Fusion.hpp"
#include "ProceduralScenario.hpp"

int main(int argc, char** argv) {
    try {
        const std::string command = argc > 1 ? argv[1] : "run";
        if (command == "fuse") return sensor_platform::fusionCommand(argc, argv);
        if (command == "replay") {
            if (argc != 3) throw std::invalid_argument("Usage: sensor_platform replay <path>");
            std::ifstream input(argv[2], std::ios::binary);
            if (!input) throw std::runtime_error("Cannot open recording: " + std::string(argv[2]));
            // No simulation on this path. Read/validate the entire run before output.
            const auto events = sensor_platform::readRecording(input);
            sensor_platform::writeRecording(std::cout, events);
            return 0;
        }
        if (command != "run" && command != "observe") throw std::invalid_argument("Usage: sensor_platform run|observe [options] | replay <path>");
        sensor_sandbox::RunId runId = 1;
        std::string recordPath;
        std::string experiment;
        std::string proceduralPath, layoutOutput;
        sensor_platform::ObservationOptions observationOptions;
        bool hasRunId = false;
        int sampleSeconds = 1;
        bool hasSampleSeconds = false;
        for (int i = 2; i < argc; ++i) {
            const std::string option = argv[i];
            if (++i == argc) throw std::invalid_argument("Missing value for " + option);
            const std::string value = argv[i];
            auto nonnegative = [&] {
                int number{};
                const auto parsed = std::from_chars(value.data(), value.data() + value.size(), number);
                if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || number < 0)
                    throw std::invalid_argument("Expected nonnegative integer for " + option);
                return number;
            };
            if (option == "--sample-seconds" && command == "run" && !hasSampleSeconds) {
                sampleSeconds = nonnegative();
                if (sampleSeconds < 1 || sampleSeconds > 3600)
                    throw std::invalid_argument("--sample-seconds must be between 1 and 3600");
                hasSampleSeconds = true;
            }
            else if (option == "--experiment" && command == "run") experiment = value;
            else if (option == "--procedural" && command == "run" && proceduralPath.empty() && !value.empty()) proceduralPath = value;
            else if (option == "--layout-output" && command == "run" && layoutOutput.empty() && !value.empty()) layoutOutput = value;
            else if (option == "--metrics") observationOptions.metrics = value;
            else if (option == "--delay-ms" && command == "observe") observationOptions.delayMs = nonnegative();
            else if (option == "--pause-after" && command == "observe") observationOptions.pauseAfter = nonnegative();
            else if (option == "--pause-ms" && command == "observe") observationOptions.pauseMs = nonnegative();
            else if (option == "--record" && command == "run" && recordPath.empty() && !value.empty()) recordPath = value;
            else if (option == "--run-id" && command == "run" && !hasRunId) {
                const auto parsed = std::from_chars(value.data(), value.data() + value.size(), runId);
                if (parsed.ec != std::errc{} || parsed.ptr != value.data() + value.size() || runId == 0)
                    throw std::invalid_argument("Run ID must be a positive integer");
                hasRunId = true;
            } else throw std::invalid_argument("Unknown or duplicate option: " + option);
        }
        if (hasSampleSeconds && !experiment.empty())
            throw std::invalid_argument("--sample-seconds cannot be combined with --experiment");
        if (!proceduralPath.empty() && (hasSampleSeconds || !experiment.empty()))
            throw std::invalid_argument("--procedural cannot be combined with --sample-seconds or --experiment");
        if (!layoutOutput.empty() && proceduralPath.empty())
            throw std::invalid_argument("--layout-output requires --procedural");
        std::optional<sensor_platform::GeneratedScenario> generated;
        if (!proceduralPath.empty()) {
            std::ifstream input(proceduralPath);
            if (!input) throw std::runtime_error("Cannot open procedural configuration: " + proceduralPath);
            generated = sensor_platform::generateScenario(sensor_platform::readProceduralConfig(input));
            if (!layoutOutput.empty()) {
                std::ofstream output(layoutOutput);
                if (!output) throw std::runtime_error("Cannot create sensor layout: " + layoutOutput);
                sensor_platform::writeScenarioLayout(output, *generated);
                output.close();
                if (!output) throw std::runtime_error("Cannot close sensor layout: " + layoutOutput);
            }
        }
        sensor_platform::Observation observation(observationOptions);
        sensor_platform::IncrementalRecording live(std::cout);
        if (command == "observe") {
            std::string line;
            if (!std::getline(std::cin, line) || line != "SENSOR_EVENTS 1")
                throw std::invalid_argument("Invalid input recording header");
            while (std::getline(std::cin, line)) {
                const auto event = sensor_platform::deserializeEvent("SENSOR_EVENTS 1\n" + line + "\n");
                observation.beforeConsume();
                live.append(event);
                observation.mark("consumed", event.identity.streamSequence);
            }
            live.finish();
            return 0;
        }
        auto produce = [&](const sensor_platform::EventSink& sink) {
            auto measured = [&](const auto& event) {
                observation.mark("produced", event.identity.streamSequence);
                sink(event);
            };
            if (generated) sensor_platform::runProcedural(runId, *generated, measured);
            else if (experiment.empty()) sensor_platform::runSample(runId, measured, sampleSeconds);
            else sensor_platform::runExperiment(runId, experiment, measured);
        };
        if (!recordPath.empty()) {
            std::ofstream output(recordPath, std::ios::binary | std::ios::trunc);
            if (!output) throw std::runtime_error("Cannot create recording: " + recordPath);
            sensor_platform::IncrementalRecording recording(output);
            produce([&](const auto& event) {
                recording.append(event);
                live.append(event);
            });
            recording.finish();
            output.close();
            if (!output) throw std::runtime_error("Failed to close recording: " + recordPath);
        } else {
            produce([&](const auto& event) { live.append(event); });
        }
        live.finish();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
