#pragma once

#include <iosfwd>
#include <vector>

#include "sensor/events/StreamEvent.hpp"

namespace sensor_platform {

// Validate a complete stream, including lifecycle/order and the required final event.
void validateEvents(const std::vector<sensor_sandbox::StreamEvent>& events);
// Versioned text; float max_digits10 preserves the exact original values.
void writeRecording(std::ostream& output, const std::vector<sensor_sandbox::StreamEvent>& events);
// Loads and validates everything before the caller can deliver events to a consumer.
std::vector<sensor_sandbox::StreamEvent> readRecording(std::istream& input);
// The same observable consumer for live and replayed typed events.
void printEvent(std::ostream& output, const sensor_sandbox::StreamEvent& event);

} // namespace sensor_platform
