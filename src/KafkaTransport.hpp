#pragma once
#include <cstddef>
#include <string>
#include "sensor/events/StreamEvent.hpp"
#include "Experiment.hpp"
namespace sensor_platform {
struct KafkaOptions {
    std::string brokers{"localhost:9092"};
    std::string topic;
    std::string group;
    std::string output;
    int timeoutMs{15000};
    std::size_t maxEvents{}; // Viewer only: orderly checkpoint for restart demonstrations.
    std::string experiment;
    ObservationOptions observation;
};
void publishKafka(const KafkaOptions& options, sensor_sandbox::RunId runId);
void consumeKafka(const KafkaOptions& options, bool record);
}
