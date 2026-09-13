#pragma once
#include <istream>
#include <string>
#include <vector>

namespace sensor_platform::viewer {
struct ResultPoint {
    double value{}, mean{}, deviation{}, minimum{}, maximum{};
    int runs{}, valid{};
};
struct ResultChart {
    std::string id, title, unit, definition, finding;
    std::vector<ResultPoint> points;
};
struct ResultPanel {
    std::string id, title, axis;
    std::vector<ResultChart> charts;
};
struct StudyResults {
    std::string title, question, identity;
    int runs{}, seeds{};
    std::vector<ResultPanel> panels;
};
// Display-only aggregate contract: no recording, simulation or fusion dependency.
StudyResults readStudyResults(std::istream& input);
int resultsCommand(int argc, char** argv);
}
