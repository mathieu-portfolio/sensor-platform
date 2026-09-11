#include "KafkaTransport.hpp"
#include <charconv>
#include <iostream>
#include <map>
#include <type_traits>
#include <stdexcept>

namespace {
template<class T> T positive(const std::string& text) {
    T value{};
    const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
    if (parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() || value == 0)
        throw std::invalid_argument("Expected positive integer: " + text);
    if constexpr (std::is_signed_v<T>) {
        if (value < 0) throw std::invalid_argument("Expected positive integer");
    }
    return value;
}
}
int main(int argc, char** argv) {
    try {
        if (argc < 2) throw std::invalid_argument("Usage: sensor_platform_kafka producer|consumer|recorder --topic <run-topic> [--brokers localhost:9092] [--run-id 42] [--group <group>] [--output <file>] [--max-events N] [--timeout-ms 15000]");
        const std::string mode = argv[1];
        if (mode != "producer" && mode != "consumer" && mode != "recorder")
            throw std::invalid_argument("Unknown Kafka mode");
        std::map<std::string, std::string> args;
        for (int i = 2; i < argc; i += 2) {
            if (i + 1 >= argc || !args.emplace(argv[i], argv[i + 1]).second)
                throw std::invalid_argument("Missing or duplicate option");
        }
        sensor_platform::KafkaOptions options;
        sensor_sandbox::RunId runId = 1;
        for (const auto& [key, value] : args) {
            if (value.empty()) throw std::invalid_argument("Empty option");
            if (key == "--brokers") options.brokers = value;
            else if (key == "--topic") options.topic = value;
            else if (key == "--group" && mode != "producer") options.group = value;
            else if (key == "--output" && mode == "recorder") options.output = value;
            else if (key == "--run-id" && mode == "producer") runId = positive<sensor_sandbox::RunId>(value);
            else if (key == "--experiment" && mode == "producer") options.experiment = value;
            else if (key == "--metrics") options.observation.metrics = value;
            else if (key == "--delay-ms" && mode != "producer") options.observation.delayMs = positive<int>(value);
            else if (key == "--pause-after" && mode != "producer") options.observation.pauseAfter = positive<std::size_t>(value);
            else if (key == "--pause-ms" && mode != "producer") options.observation.pauseMs = positive<int>(value);
            else if (key == "--max-events" && mode == "consumer") options.maxEvents = positive<std::size_t>(value);
            else if (key == "--timeout-ms") options.timeoutMs = positive<int>(value);
            else throw std::invalid_argument("Unsupported option for mode: " + key);
        }
        if (options.topic.empty() || (mode != "producer" && options.group.empty()) ||
            (mode == "recorder" && options.output.empty()))
            throw std::invalid_argument("--topic required; consumers need --group; recorder needs --output");
        if (mode == "producer") sensor_platform::publishKafka(options, runId);
        else sensor_platform::consumeKafka(options, mode == "recorder");
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
