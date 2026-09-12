#pragma once
#include <functional>
#include "sensor/events/StreamEvent.hpp"
namespace sensor_platform {
// The only delivery boundary: synchronously accept one concrete domain event.
using EventSink = std::function<void(const sensor_sandbox::StreamEvent&)>;
void runSample(sensor_sandbox::RunId runId, const EventSink& sink, int seconds = 1);
}
