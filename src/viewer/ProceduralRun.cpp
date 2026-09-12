#include "ProceduralRun.hpp"
#include <sstream>
#include <stdexcept>

namespace sensor_platform::viewer {
ProceduralFields::ProceduralFields() {
    const ProceduralConfig defaults;
    values = {std::to_string(defaults.scenarioSeed), std::to_string(defaults.layoutSeed),
              std::to_string(defaults.durationSeconds), std::to_string(defaults.targetCount),
              std::to_string(defaults.sensorCount)};
    for (std::size_t i = 0; i < parameters.size(); ++i) {
        std::ostringstream text;
        text.imbue(std::locale::classic());
        text << defaults.*(proceduralParameters[i].member);
        parameters[i] = text.str();
    }
}

ProceduralConfig ProceduralFields::config() const {
    std::string text = "SENSOR_PROCEDURAL 2\n";
    for (const auto& value : values) {
        // An empty field must not borrow the next field's token. Reject whitespace
        // as well so this adapter cannot change the runtime's five-value mapping.
        if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
            throw std::invalid_argument("Enter a whole number in every field");
        text += value + ' ';
    }
    for (const auto& value : parameters) {
        if (value.empty() || value.find_first_not_of("0123456789.") != std::string::npos)
            throw std::invalid_argument("Enter a number in every parameter field");
        text += value + ' ';
    }
    std::istringstream input(text);
    return readProceduralConfig(input);
}

PreparedRecording prepareProceduralRecording(const ProceduralConfig& config) {
    const auto scenario = generateScenario(config);
    std::ostringstream recording;
    IncrementalRecording writer(recording);
    runProcedural(43, scenario, [&](const auto& event) { writer.append(event); });
    writer.finish();
    std::istringstream recorded(recording.str());
    std::ostringstream geometry;
    writeScenarioLayout(geometry, scenario);
    std::istringstream layout(geometry.str());
    return {readRecording(recorded), readLayout(layout)};
}
}
