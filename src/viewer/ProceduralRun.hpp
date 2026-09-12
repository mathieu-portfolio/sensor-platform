#pragma once

#include "ProceduralScenario.hpp"
#include "ViewerState.hpp"
#include <array>
#include <string>

namespace sensor_platform::viewer {
// Text inputs share the runtime's configuration defaults, parser and limits.
struct ProceduralFields {
    ProceduralFields();
    std::array<std::string, 5> values;
    ProceduralConfig config() const;
};

struct PreparedRecording {
    std::vector<sensor_sandbox::StreamEvent> events;
    std::vector<SensorGeometry> layout;
};

// Complete the normal run/record/decode path before playback receives anything.
// No rendering, filesystem writes, custom fusion or simulation on playback ticks.
PreparedRecording prepareProceduralRecording(const ProceduralConfig& config);
}
