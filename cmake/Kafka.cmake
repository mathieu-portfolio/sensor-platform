# Optional native Kafka adapter; default local builds have no Kafka dependency.
find_package(RdKafka CONFIG QUIET)
if(NOT TARGET RdKafka::rdkafka)
    include(FetchContent)
    set(RDKAFKA_BUILD_STATIC ON CACHE BOOL "" FORCE)
    set(RDKAFKA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(RDKAFKA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(WITH_SSL OFF CACHE BOOL "" FORCE)
    set(WITH_SASL OFF CACHE BOOL "" FORCE)
    set(WITH_CURL OFF CACHE BOOL "" FORCE)
    set(WITH_ZLIB OFF CACHE BOOL "" FORCE)
    set(WITH_ZSTD OFF CACHE BOOL "" FORCE)
    set(ENABLE_LZ4_EXT OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(librdkafka
        GIT_REPOSITORY https://github.com/confluentinc/librdkafka.git
        GIT_TAG v2.10.1
        GIT_SHALLOW TRUE)
    FetchContent_MakeAvailable(librdkafka)
    add_library(RdKafka::rdkafka ALIAS rdkafka)
endif()
