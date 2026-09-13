#include "Results.hpp"
#include <algorithm>
#include <cmath>
#include <iomanip>
#include <set>
#include <sstream>
#include <stdexcept>

namespace sensor_platform::viewer {
StudyResults readStudyResults(std::istream& input) {
    auto fail = [] { throw std::invalid_argument("Invalid or incomplete SENSOR_STUDY results; generate study analysis first"); };
    std::string line;
    if (!std::getline(input, line)) fail();
    if (!line.empty() && line.back() == '\r') line.pop_back();
    if (line != "SENSOR_STUDY 1") fail();
    StudyResults result;
    bool started = false, ended = false;
    std::size_t lines = 0;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        if (++lines > 200 || line.size() > 8192 || ended) fail();
        std::istringstream row(line);
        std::string kind;
        row >> kind;
        if (kind == "STUDY") {
            if (started || !(row >> std::quoted(result.title) >> std::quoted(result.question) >> std::quoted(result.identity) >> result.runs >> result.seeds)) fail();
            if (result.title.empty() || result.question.empty() || result.runs < 1 || result.runs > 100000 || result.seeds < 1 || result.seeds > result.runs) fail();
            started = true;
        } else if (kind == "PANEL") {
            ResultPanel panel;
            if (!started || !(row >> std::quoted(panel.id) >> std::quoted(panel.title) >> std::quoted(panel.axis))) fail();
            if (panel.title.empty() || panel.axis.empty() || std::any_of(result.panels.begin(), result.panels.end(), [&](const auto& p) {return p.id == panel.id;})) fail();
            result.panels.push_back(std::move(panel));
        } else if (kind == "CHART") {
            std::string panel;
            ResultChart chart;
            if (result.panels.empty() || !(row >> std::quoted(panel) >> std::quoted(chart.id) >> std::quoted(chart.title) >> std::quoted(chart.unit) >> std::quoted(chart.definition) >> std::quoted(chart.finding))) fail();
            auto& p = result.panels.back();
            if (panel != p.id || chart.title.empty() || chart.unit.empty() || std::any_of(p.charts.begin(), p.charts.end(), [&](const auto& c) {return c.id == chart.id;})) fail();
            p.charts.push_back(std::move(chart));
        } else if (kind == "POINT") {
            std::string panel, chart;
            ResultPoint point;
            if (result.panels.empty() || result.panels.back().charts.empty() || !(row >> std::quoted(panel) >> std::quoted(chart) >> point.value >> point.runs >> point.valid >> point.mean >> point.deviation >> point.minimum >> point.maximum)) fail();
            auto& p = result.panels.back();
            auto& c = p.charts.back();
            if (panel != p.id || chart != c.id || point.runs != result.seeds || point.valid < 0 || point.valid > point.runs ||
                !std::isfinite(point.value) || !std::isfinite(point.mean) || !std::isfinite(point.deviation) || !std::isfinite(point.minimum) || !std::isfinite(point.maximum) ||
                point.value < 0 || point.deviation < 0 || point.minimum < 0 || point.mean < point.minimum || point.mean > point.maximum ||
                (!c.points.empty() && point.value <= c.points.back().value)) fail();
            c.points.push_back(point);
        } else if (kind == "END") {
            ended = true;
        } else fail();
        std::string extra;
        if (row >> extra) fail();
    }
    if (!ended || input.bad() || result.panels.size() != 5) fail();
    const std::vector<std::string> names{"noise", "reliability", "clutter", "convergence", "sensor_network"};
    int total = 0;
    for (std::size_t i = 0; i < names.size(); ++i) {
        const auto& p = result.panels[i];
        if (p.id != names[i] || p.charts.size() < 2 || p.charts.size() > 3) fail();
        const auto& reference = p.charts.front().points;
        if (reference.size() < 2 || reference.size() > 5) fail();
        total += static_cast<int>(reference.size()) * result.seeds;
        for (const auto& c : p.charts) {
            if (c.points.size() != reference.size()) fail();
            for (std::size_t j = 0; j < reference.size(); ++j)
                if (c.points[j].value != reference[j].value) fail();
        }
    }
    if (total != result.runs) fail();
    return result;
}
}
