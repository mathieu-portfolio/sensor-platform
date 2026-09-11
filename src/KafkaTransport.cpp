#include "KafkaTransport.hpp"
#include "EventRecording.hpp"
#include "EventTransport.hpp"

#if __has_include(<librdkafka/rdkafka.h>)
#include <librdkafka/rdkafka.h>
#else
#include <rdkafka.h>
#endif

#include <chrono>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <thread>

namespace sensor_platform {
namespace {
void checked(rd_kafka_resp_err_t error, const char* action) {
    if (error) throw std::runtime_error(std::string(action) + ": " + rd_kafka_err2str(error));
}
using Config = std::unique_ptr<rd_kafka_conf_t, decltype(&rd_kafka_conf_destroy)>;
using Topic = std::unique_ptr<rd_kafka_topic_t, decltype(&rd_kafka_topic_destroy)>;
using Partitions = std::unique_ptr<rd_kafka_topic_partition_list_t, decltype(&rd_kafka_topic_partition_list_destroy)>;
using Message = std::unique_ptr<rd_kafka_message_t, decltype(&rd_kafka_message_destroy)>;

void set(rd_kafka_conf_t* conf, const char* name, const std::string& value) {
    char error[512];
    if (rd_kafka_conf_set(conf, name, value.c_str(), error, sizeof(error)) != RD_KAFKA_CONF_OK)
        throw std::runtime_error(std::string(name) + ": " + error);
}
struct Client {
    rd_kafka_t* handle{};
    bool consumer{};
    Client(rd_kafka_type_t type, Config config) : consumer(type == RD_KAFKA_CONSUMER) {
        char error[512];
        handle = rd_kafka_new(type, config.get(), error, sizeof(error));
        if (!handle) throw std::runtime_error(error);
        config.release(); // Client owns configuration after successful creation.
    }
    ~Client() {
        if (handle) {
            if (consumer) rd_kafka_consumer_close(handle);
            rd_kafka_destroy(handle);
        }
    }
    Client(const Client&) = delete;
    Client& operator=(const Client&) = delete;
};

Config configFor(const KafkaOptions& options) {
    Config config(rd_kafka_conf_new(), rd_kafka_conf_destroy);
    set(config.get(), "bootstrap.servers", options.brokers);
    set(config.get(), "socket.timeout.ms", std::to_string(options.timeoutMs));
    set(config.get(), "allow.auto.create.topics", "false");
    return config;
}

std::pair<std::int64_t, std::int64_t> inspect(Client& client, const KafkaOptions& options) {
    Topic topic(rd_kafka_topic_new(client.handle, options.topic.c_str(), nullptr), rd_kafka_topic_destroy);
    if (!topic) throw std::runtime_error("Cannot create topic handle");
    const rd_kafka_metadata_t* raw{};
    checked(rd_kafka_metadata(client.handle, 0, topic.get(), &raw, options.timeoutMs), "Topic metadata");
    std::unique_ptr<const rd_kafka_metadata_t, decltype(&rd_kafka_metadata_destroy)> metadata(raw, rd_kafka_metadata_destroy);
    if (raw->topic_cnt != 1 || raw->topics[0].err || raw->topics[0].partition_cnt != 1)
        throw std::runtime_error("Topic must exist and have exactly one partition");
    std::int64_t low{}, high{};
    checked(rd_kafka_query_watermark_offsets(client.handle, options.topic.c_str(), 0, &low, &high,
                                             options.timeoutMs), "Topic offsets");
    if (low != 0) throw std::runtime_error("Run prefix expired: use a fully retained run topic");
    return {low, high};
}

void delivery(rd_kafka_t*, const rd_kafka_message_t* message, void* opaque) {
    if (message->err) *static_cast<rd_kafka_resp_err_t*>(opaque) = message->err;
}

// A newly started single broker may still be electing/loading the offsets coordinator.
template<class Operation> void coordinatorOperation(Operation operation, int timeoutMs, const char* action) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs);
    for (;;) {
        const auto error = operation();
        if (!error) return;
        const bool retryable = error == RD_KAFKA_RESP_ERR_NOT_COORDINATOR ||
            error == RD_KAFKA_RESP_ERR_COORDINATOR_NOT_AVAILABLE ||
            error == RD_KAFKA_RESP_ERR_COORDINATOR_LOAD_IN_PROGRESS ||
            error == RD_KAFKA_RESP_ERR__WAIT_COORD || error == RD_KAFKA_RESP_ERR__TIMED_OUT;
        if (!retryable || std::chrono::steady_clock::now() >= deadline) checked(error, action);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
}
} // namespace

void publishKafka(const KafkaOptions& options, sensor_sandbox::RunId runId) {
    auto config = configFor(options);
    set(config.get(), "enable.idempotence", "true");
    set(config.get(), "acks", "all");
    set(config.get(), "delivery.timeout.ms", std::to_string(options.timeoutMs));
    set(config.get(), "request.timeout.ms", std::to_string(options.timeoutMs));
    rd_kafka_resp_err_t deliveryError = RD_KAFKA_RESP_ERR_NO_ERROR;
    rd_kafka_conf_set_opaque(config.get(), &deliveryError);
    rd_kafka_conf_set_dr_msg_cb(config.get(), delivery);
    Client client(RD_KAFKA_PRODUCER, std::move(config));
    if (inspect(client, options).second != 0)
        throw std::runtime_error("Producer requires an empty run topic; do not republish into an existing run");
    Topic topic(rd_kafka_topic_new(client.handle, options.topic.c_str(), nullptr), rd_kafka_topic_destroy);
    if (!topic) throw std::runtime_error("Cannot create topic handle");
    EventValidator validator;
    Observation observation(options.observation);
    const EventSink sink = [&](const auto& event) {
        validator.accept(event);
        const auto payload = serializeEvent(event);
        const auto key = std::to_string(event.identity.runId);
        observation.mark("produced", event.identity.streamSequence);
        if (rd_kafka_produce(topic.get(), 0, RD_KAFKA_MSG_F_COPY,
                             const_cast<char*>(payload.data()), payload.size(),
                             key.data(), key.size(), nullptr) != 0)
            checked(rd_kafka_last_error(), "Publish");
        // Modest synchronous boundary: next event waits for acknowledged delivery.
        checked(rd_kafka_flush(client.handle, options.timeoutMs), "Delivery timeout");
        checked(deliveryError, "Delivery failed");
    };
    if (options.experiment.empty()) runSample(runId, sink);
    else runExperiment(runId, options.experiment, sink);
    validator.finish();
}

void consumeKafka(const KafkaOptions& options, bool record) {
    Observation observation(options.observation);
    auto config = configFor(options);
    set(config.get(), "group.id", options.group);
    set(config.get(), "enable.auto.commit", "false");
    set(config.get(), "enable.auto.offset.store", "false");
    set(config.get(), "auto.offset.reset", "error");
    Client client(RD_KAFKA_CONSUMER, std::move(config));
    checked(rd_kafka_poll_set_consumer(client.handle), "Consumer queue");
    const auto high = inspect(client, options).second;
    Partitions partitions(rd_kafka_topic_partition_list_new(1), rd_kafka_topic_partition_list_destroy);
    auto* partition = rd_kafka_topic_partition_list_add(partitions.get(), options.topic.c_str(), 0);
    coordinatorOperation([&] { return rd_kafka_committed(client.handle, partitions.get(), 1000); },
                         options.timeoutMs, "Read committed offset");
    checked(partition->err, "Committed partition");
    const auto committed = partition->offset == RD_KAFKA_OFFSET_INVALID ? 0 : partition->offset;
    if (committed < 0 || committed > high) throw std::runtime_error("Invalid committed offset for retained run");
    // Rebuild validation from prefix. Only the viewer suppresses already committed output.
    // Manual assignment: exactly one active process per group, no group rebalancing.
    partition->offset = 0;
    checked(rd_kafka_assign(client.handle, partitions.get()), "Assign partition");

    std::ofstream file;
    std::unique_ptr<IncrementalRecording> recording;
    if (record) {
        file.open(options.output, std::ios::binary | std::ios::trunc);
        if (!file) throw std::runtime_error("Cannot create recording: " + options.output);
        recording = std::make_unique<IncrementalRecording>(file);
    } else if (committed == 0) {
        std::cout << "SENSOR_EVENTS 1\n";
        std::cout.flush();
        if (!std::cout) throw std::runtime_error("Cannot write viewer header");
    }
    EventValidator validator;
    std::size_t delivered{};
    std::int64_t expectedOffset{};
    auto lastMessage = std::chrono::steady_clock::now();
    for (;;) {
        Message message(rd_kafka_consumer_poll(client.handle, 100), rd_kafka_message_destroy);
        if (!message) {
            if (std::chrono::steady_clock::now() - lastMessage > std::chrono::milliseconds(options.timeoutMs))
                throw std::runtime_error("Timed out before RUN_FINISHED; partial recording is not replayable");
            continue;
        }
        checked(message->err, "Consume");
        if (message->partition != 0 || message->offset != expectedOffset++)
            throw std::runtime_error("Missing or unexpected Kafka offset");
        lastMessage = std::chrono::steady_clock::now();
        const auto event = deserializeEvent(std::string(static_cast<const char*>(message->payload), message->len));
        const std::string key(message->key ? static_cast<const char*>(message->key) : "", message->key_len);
        if (key != std::to_string(event.identity.runId)) throw std::runtime_error("Kafka key/run identity mismatch");
        validator.accept(event); // Duplicates/gaps fail before output or offset commit.
        if (message->offset >= committed) observation.beforeConsume();
        if (recording) recording->append(event);
        else if (message->offset >= committed) {
            printEvent(std::cout, event);
            std::cout.flush();
            if (!std::cout) throw std::runtime_error("Viewer output failed");
        }
        if (message->offset >= committed) {
            observation.mark("consumed", event.identity.streamSequence);
            // Commit only after the output/file flush succeeded. This is not a transaction.
            coordinatorOperation([&] { return rd_kafka_commit_message(client.handle, message.get(), 0); },
                                 options.timeoutMs, "Commit processed offset");
            ++delivered;
        }
        if (validator.complete()) {
            validator.finish();
            if (recording) {
                recording->finish();
                file.close();
                if (!file) throw std::runtime_error("Recording close failed");
            }
            std::cerr << "Run complete; newly committed events=" << delivered << '\n';
            return;
        }
        if (!record && options.maxEvents && delivered >= options.maxEvents) {
            std::cerr << "Viewer checkpoint; newly committed events=" << delivered << '\n';
            return;
        }
    }
}
} // namespace sensor_platform
