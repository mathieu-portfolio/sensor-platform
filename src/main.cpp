#include <iomanip>
#include <iostream>

#include "sensor/sensors/SensorSystem.hpp"
#include "sensor/world/EntityMotionSystem.hpp"
#include "sensor/world/WorldState.hpp"

int main() {
    using namespace sensor_sandbox;

    // A scripted scenario: one entity moving along +X in local world units.
    WorldState world;
    Entity entity;
    entity.id = 1;
    entity.label = "Straight transit";
    entity.position = {100.0f, 0.0f};
    entity.velocity = {10.0f, 0.0f};
    world.entities().push_back(entity);

    Sensor sensor;
    sensor.id = 1;
    sensor.label = "Headless radar";
    sensor.definition.refreshRateHz = 2.0f;
    // Defaults: full-circle coverage, no noise, no drops or false returns.
    world.sensors().push_back(sensor);

    EntityMotionSystem motion;
    SensorSystem scanner;
    constexpr float stepSeconds = 0.25f;
    std::cout << std::fixed << std::setprecision(2);
    for (int step = 0; step <= 4; ++step) {
        if (step > 0) {
            motion.update(world, stepSeconds);
        }
        const float simulationSeconds = static_cast<float>(step) * stepSeconds;
        const auto scan = scanner.scan(world.sensors().front(), world.entities(), simulationSeconds);
        if (!scan) {
            continue;
        }
        std::cout << "sensor=" << scan->sensorId << " scan=" << scan->sequence
                  << " time=" << scan->simulationTimeSeconds
                  << " measurements=" << scan->detections.size() << '\n';
        for (const auto& measurement : scan->detections) {
            std::cout << "  detection=" << measurement.id
                      << " position=(" << measurement.estimatedPosition.x
                      << ", " << measurement.estimatedPosition.y << ")\n";
        }
    }
}
