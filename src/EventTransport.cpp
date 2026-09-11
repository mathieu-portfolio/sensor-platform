#include "EventTransport.hpp"
#include "RunSession.hpp"

void sensor_platform::runSample(sensor_sandbox::RunId runId, const EventSink& sink) {
    using namespace sensor_sandbox;
    using sensor_platform::SensorConfig;

    Entity entity;
    entity.id = 1;
    entity.label = "Straight transit";
    entity.position = {100.0f, 0.0f};
    entity.velocity = {10.0f, 0.0f};

    // Concrete in-process configuration; each seed belongs to its sensor ID.
    const std::vector<SensorConfig> configs{
        {.id = 1, .position = {0, 0},
         .definition = {.range = 200, .refreshRateHz = 1}, .seed = 11},
        {.id = 2, .position = {50, 20},
         .definition = {.range = 150, .refreshRateHz = 2}, .seed = 22},
        {.id = 3, .position = {150, -20},
         .definition = {.range = 100, .refreshRateHz = 4, .rangeNoise = 2,
                        .detectionProbability = 0.75f, .falsePositiveRateHz = 1}, .seed = 33}
    };
    sensor_platform::RunSession session(runId, {entity}, configs);
    for (const auto& event : session.start()) sink(event);
    for (int step = 0; step <= 4; ++step) {
        auto batch = session.advanceTo(static_cast<float>(step) * 0.25f);
        for (const auto& event : batch) sink(event);
    }
    sink(session.finish());
}
