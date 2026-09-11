#include "Fusion.hpp"
#include <charconv>
#include <fstream>
#include <iostream>
#include <set>
#include <stdexcept>

namespace sensor_platform {
int fusionCommand(int argc, char** argv) {
    if (argc < 3) throw std::invalid_argument("Usage: sensor_platform fuse <recording|-> [--output path] [--gate N] [--alpha N] [--beta N] [--coast-after N] [--delete-after N] [--tentative-timeout N] [--confirmation-times N]");
    FusionConfig config;
    std::string path;
    std::set<std::string> seen;
    for (int i = 3; i < argc; i += 2) {
        const std::string key = argv[i];
        if (i + 1 >= argc || !seen.insert(key).second) throw std::invalid_argument("Missing or duplicate fusion option");
        const std::string value = argv[i + 1];
        if (key == "--output") { path = value; continue; }
        auto number = [&]<class T>(T& field) {
            const auto p = std::from_chars(value.data(), value.data() + value.size(), field);
            if (p.ec != std::errc{} || p.ptr != value.data() + value.size()) throw std::invalid_argument("Invalid numeric fusion option");
        };
        if (key == "--gate") number(config.gateDistance);
        else if (key == "--alpha") number(config.positionGain);
        else if (key == "--beta") number(config.velocityGain);
        else if (key == "--coast-after") number(config.coastAfter);
        else if (key == "--delete-after") number(config.deleteAfter);
        else if (key == "--tentative-timeout") number(config.tentativeTimeout);
        else if (key == "--confirmation-times") number(config.confirmationTimes);
        else throw std::invalid_argument("Unknown fusion option: " + key);
    }
    FusionSystem fusion(config);
    const bool streaming = std::string(argv[2]) == "-";
    std::vector<sensor_sandbox::StreamEvent> events;
    if (!streaming) {
        std::ifstream input(argv[2], std::ios::binary);
        if (!input) throw std::runtime_error("Cannot open fusion input");
        events = readRecording(input); // Validate the complete source before opening output.
    }
    std::ofstream file;
    if (!path.empty()) {
        file.open(path, std::ios::binary | std::ios::trunc);
        if (!file) throw std::runtime_error("Cannot open fusion output");
    }
    std::ostream& output = path.empty() ? std::cout : file;
    auto consume = [&](const auto& event) { printGlobalTrackEvent(output, fusion.accept(event), config); };
    if (streaming) {
        std::string header, line;
        if (!std::getline(std::cin, header) || header != "SENSOR_EVENTS 1")
            throw std::invalid_argument("Expected complete stream beginning with SENSOR_EVENTS 1");
        while (std::getline(std::cin, line)) consume(deserializeEvent("SENSOR_EVENTS 1\n" + line + "\n"));
        if (std::cin.bad()) throw std::runtime_error("Fusion stream read failed");
    } else for (const auto& event : events) consume(event);
    fusion.finish();
    if (file.is_open()) { file.close(); if (!file) throw std::runtime_error("Fusion output close failed"); }
    return 0;
}
}
