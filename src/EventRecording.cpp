#include "EventRecording.hpp"

#include <charconv>
#include <cmath>
#include <iomanip>
#include <istream>
#include <limits>
#include <locale>
#include <map>
#include <ostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <type_traits>

namespace sensor_platform {
using namespace sensor_sandbox;

namespace {
[[noreturn]] void invalid(const std::string& message) {
    throw std::runtime_error("Invalid recording: " + message);
}
void require(bool condition, const char* message) {
    if (!condition) invalid(message);
}
bool finite(float value) { return std::isfinite(value); }

template<class T> T number(std::istringstream& line) {
    std::string token;
    if (!(line >> token)) invalid("missing field");
    T value{};
    const auto result = std::from_chars(token.data(), token.data() + token.size(), value);
    if (result.ec != std::errc{} || result.ptr != token.data() + token.size()) invalid("invalid numeric field: " + token);
    return value;
}

StreamEvent parseLine(const std::string& text) {
    std::istringstream line(text);
    line.imbue(std::locale::classic());
    std::string type;
    if (!(line >> type)) invalid("empty event line");
    StreamEvent event;
    auto& h = event.identity;
    h.runId = number<RunId>(line);
    h.runGeneration = number<std::uint64_t>(line);
    h.streamSequence = number<std::uint64_t>(line);
    h.timeSeconds = number<float>(line);
    if (type == "RUN_STARTED") event.payload = RunStarted{};
    else if (type == "RUN_RESET") event.payload = RunReset{};
    else if (type == "RUN_FINISHED") event.payload = RunFinished{};
    else if (type == "SENSOR_STARTED") {
        const auto id = number<SensorId>(line);
        const auto generation = number<std::uint64_t>(line);
        event.payload = SensorStarted{id, generation, number<std::uint32_t>(line)};
    } else if (type == "SENSOR_RESET") {
        const auto id = number<SensorId>(line);
        event.payload = SensorReset{id, number<std::uint64_t>(line)};
    } else if (type == "MEASUREMENTS") {
        RadarMeasurements scan;
        scan.sensorId = number<SensorId>(line);
        scan.sensorGeneration = number<std::uint64_t>(line);
        scan.scanSequence = number<std::uint64_t>(line);
        const auto count = number<std::uint64_t>(line);
        // Do not allocate from an untrusted count; missing fields fail on the first absent tuple.
        for (std::uint64_t i = 0; i < count; ++i) {
            Detection d;
            d.id = number<DetectionId>(line);
            d.sensorId = scan.sensorId;
            d.estimatedPosition.x = number<float>(line);
            d.estimatedPosition.y = number<float>(line);
            d.confidence = number<float>(line);
            d.uncertaintyRadius = number<float>(line);
            scan.detections.push_back(d);
        }
        event.payload = std::move(scan);
    } else invalid("unknown event type: " + type);
    std::string extra;
    if (line >> extra) invalid("extra fields");
    return event;
}
} // namespace

void EventValidator::accept(const StreamEvent& event) {
    auto next = *this;
    next.acceptNext(event);
    *this = std::move(next);
}

void EventValidator::acceptNext(const StreamEvent& e) {
    if (sequence == 0) {
        require(std::holds_alternative<RunStarted>(e.payload), "first event must start the run");
        runId = e.identity.runId;
        require(runId != 0, "run ID must be nonzero");
    }
    const auto& h = e.identity;
    require(!finished_, "events after run finish");
    require(h.runId == runId && h.streamSequence == sequence + 1, "run ID or stream sequence mismatch");
    require(finite(h.timeSeconds) && h.timeSeconds >= 0, "invalid timestamp");
    if (std::holds_alternative<RunReset>(e.payload)) {
        require(sequence > 0 && h.runGeneration == generation + 1 && h.timeSeconds == 0, "invalid run reset");
        generation = h.runGeneration;
        lastTime = 0;
        sensors.clear();
        acceptingStarts = true;
        ++sequence; return;
    }
    require(h.runGeneration == generation && h.timeSeconds >= lastTime, "generation or time moved unexpectedly");
    lastTime = h.timeSeconds;
    if (std::holds_alternative<RunStarted>(e.payload)) {
        require(sequence == 0 && generation == 0 && h.timeSeconds == 0, "duplicate/invalid run start");
    } else if (const auto* started = std::get_if<SensorStarted>(&e.payload)) {
        require(acceptingStarts && h.timeSeconds == 0 && started->sensorGeneration == 0,
                "sensor start outside generation initialization");
        require(sensors.empty() || started->sensorId > sensors.rbegin()->first,
                "sensor starts must have unique ascending IDs");
        sensors.emplace(started->sensorId, SensorState{});
    } else if (const auto* reset = std::get_if<SensorReset>(&e.payload)) {
        acceptingStarts = false;
        const auto found = sensors.find(reset->sensorId);
        require(found != sensors.end(), "reset of unknown sensor");
        auto& state = found->second;
        require(reset->sensorGeneration == state.generation + 1, "invalid sensor generation");
        state = SensorState{reset->sensorGeneration, 0, 1};
    } else if (const auto* scan = std::get_if<RadarMeasurements>(&e.payload)) {
        acceptingStarts = false;
        const auto found = sensors.find(scan->sensorId);
        require(found != sensors.end(), "measurements from unknown sensor");
        auto& state = found->second;
        require(scan->sensorGeneration == state.generation && scan->scanSequence == state.scanSequence + 1,
                "sensor generation or scan sequence mismatch");
        ++state.scanSequence;
        for (const auto& d : scan->detections) {
            require(d.sensorId == scan->sensorId && d.id > 0 &&
                    static_cast<std::uint64_t>(d.id) == state.nextDetection++, "measurement identity mismatch");
            require(finite(d.estimatedPosition.x) && finite(d.estimatedPosition.y) &&
                    finite(d.confidence) && d.confidence >= 0 && d.confidence <= 1 &&
                    finite(d.uncertaintyRadius) && d.uncertaintyRadius >= 0, "invalid measurement value");
        }
    } else if (std::holds_alternative<RunFinished>(e.payload)) {
        finished_ = true;
    }
    ++sequence;
}

void EventValidator::finish() const {
    require(finished_, "missing RUN_FINISHED (truncated or incomplete run)");
}

void validateEvents(const std::vector<StreamEvent>& events) {
    EventValidator validator;
    for (const auto& event : events) validator.accept(event);
    validator.finish();
}

IncrementalRecording::IncrementalRecording(std::ostream& output) : output_(output) {
    output_ << "SENSOR_EVENTS 1\n";
    output_.flush();
    if (!output_) throw std::runtime_error("Failed to write recording header");
}

void IncrementalRecording::append(const StreamEvent& event) {
    validator_.accept(event);
    printEvent(output_, event);
    output_.flush();
    if (!output_) throw std::runtime_error("Failed to flush recording event");
}

void IncrementalRecording::finish() const { validator_.finish(); }

std::string serializeEvent(const StreamEvent& event) {
    std::ostringstream output;
    output << "SENSOR_EVENTS 1\n";
    printEvent(output, event);
    return output.str();
}

StreamEvent deserializeEvent(const std::string& message) {
    std::istringstream input(message);
    std::string header, line, extra;
    if (!std::getline(input, header) || header != "SENSOR_EVENTS 1" || !std::getline(input, line))
        invalid("expected version header and one event");
    auto event = parseLine(line);
    if (std::getline(input, extra)) invalid("more than one event in a transport message");
    return event;
}

void printEvent(std::ostream& output, const StreamEvent& event) {
    // Format in a private classic-locale stream so caller flags/locales cannot lose precision.
    std::ostringstream line;
    line.imbue(std::locale::classic());
    line << std::setprecision(std::numeric_limits<float>::max_digits10);
    std::visit([&](const auto& payload) {
        using T = std::decay_t<decltype(payload)>;
        if constexpr (std::is_same_v<T, RunStarted>) line << "RUN_STARTED";
        else if constexpr (std::is_same_v<T, RunReset>) line << "RUN_RESET";
        else if constexpr (std::is_same_v<T, RunFinished>) line << "RUN_FINISHED";
        else if constexpr (std::is_same_v<T, SensorStarted>) line << "SENSOR_STARTED";
        else if constexpr (std::is_same_v<T, SensorReset>) line << "SENSOR_RESET";
        else line << "MEASUREMENTS";
        const auto& h = event.identity;
        line << ' ' << h.runId << ' ' << h.runGeneration << ' ' << h.streamSequence << ' ' << h.timeSeconds;
        if constexpr (std::is_same_v<T, SensorStarted>) {
            line << ' ' << payload.sensorId << ' ' << payload.sensorGeneration << ' ' << payload.seed;
        } else if constexpr (std::is_same_v<T, SensorReset>) {
            line << ' ' << payload.sensorId << ' ' << payload.sensorGeneration;
        } else if constexpr (std::is_same_v<T, RadarMeasurements>) {
            line << ' ' << payload.sensorId << ' ' << payload.sensorGeneration << ' ' << payload.scanSequence
                 << ' ' << payload.detections.size();
            for (const auto& d : payload.detections) {
                line << ' ' << d.id << ' ' << d.estimatedPosition.x << ' ' << d.estimatedPosition.y
                     << ' ' << d.confidence << ' ' << d.uncertaintyRadius;
            }
        }
    }, event.payload);
    output << line.str() << '\n';
    if (!output) throw std::runtime_error("Failed to write event stream");
}

void writeRecording(std::ostream& output, const std::vector<StreamEvent>& events) {
    validateEvents(events);
    output << "SENSOR_EVENTS 1\n";
    for (const auto& event : events) printEvent(output, event);
    output.flush();
    if (!output) throw std::runtime_error("Failed to flush recording");
}

std::vector<StreamEvent> readRecording(std::istream& input) {
    std::string line;
    if (!std::getline(input, line)) invalid("missing format header");
    if (!line.empty() && line.back() == '\r') line.pop_back();
    require(line == "SENSOR_EVENTS 1", "unsupported format/version");
    std::vector<StreamEvent> events;
    std::size_t lineNumber = 1;
    while (std::getline(input, line)) {
        ++lineNumber;
        try {
            events.push_back(parseLine(line));
        } catch (const std::exception& error) {
            throw std::runtime_error("Recording line " + std::to_string(lineNumber) + ": " + error.what());
        }
    }
    if (input.bad() || !input.eof()) invalid("read failure");
    validateEvents(events);
    return events;
}

} // namespace sensor_platform
