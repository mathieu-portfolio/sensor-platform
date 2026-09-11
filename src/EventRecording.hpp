#pragma once

#include <iosfwd>
#include <map>
#include <string>
#include <vector>

#include "sensor/events/StreamEvent.hpp"

namespace sensor_platform {

// Bounded state: no event history. Rejected events leave the validator unchanged.
class EventValidator {
public:
    void accept(const sensor_sandbox::StreamEvent& event);
    void finish() const;
    bool complete() const { return finished_; }
private:
    void acceptNext(const sensor_sandbox::StreamEvent& event);
    struct SensorState {
        std::uint64_t generation{};
        std::uint64_t scanSequence{};
        std::uint64_t nextDetection{1};
    };
    sensor_sandbox::RunId runId{};
    std::uint64_t generation{};
    std::uint64_t sequence{};
    float lastTime{};
    bool finished_{};
    bool acceptingStarts{true};
    std::map<sensor_sandbox::SensorId, SensorState> sensors;
};

// Header immediately, then one validated/flushed event per append. No run buffer.
class IncrementalRecording {
public:
    explicit IncrementalRecording(std::ostream& output);
    void append(const sensor_sandbox::StreamEvent& event);
    void finish() const;
private:
    std::ostream& output_;
    EventValidator validator_;
};

// One Kafka value is the existing version header plus exactly one event record.
std::string serializeEvent(const sensor_sandbox::StreamEvent& event);
sensor_sandbox::StreamEvent deserializeEvent(const std::string& message);

// Validate a complete stream, including lifecycle/order and the required final event.
void validateEvents(const std::vector<sensor_sandbox::StreamEvent>& events);
// Versioned text; float max_digits10 preserves the exact original values.
void writeRecording(std::ostream& output, const std::vector<sensor_sandbox::StreamEvent>& events);
// Loads and validates everything before the caller can deliver events to a consumer.
std::vector<sensor_sandbox::StreamEvent> readRecording(std::istream& input);
// The same observable consumer for live and replayed typed events.
void printEvent(std::ostream& output, const sensor_sandbox::StreamEvent& event);

} // namespace sensor_platform
