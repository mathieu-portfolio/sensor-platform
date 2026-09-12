cmake_minimum_required(VERSION 3.20)
# CMake owns dependency deployment, including when vcpkg is integrated globally
# with Visual Studio or supplied as a CMake toolchain.
set(CMAKE_VS_GLOBALS ${CMAKE_VS_GLOBALS} "VcpkgApplocalDeps=false")
set(VCPKG_APPLOCAL_DEPS OFF)
project(sensor_platform LANGUAGES CXX)

set(SENSOR_SANDBOX_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../sensor-sandbox"
    CACHE PATH "Path to the sibling sensor-sandbox checkout")
if(NOT EXISTS "${SENSOR_SANDBOX_SOURCE_DIR}/CMakeLists.txt")
    message(FATAL_ERROR "sensor-sandbox checkout missing: set SENSOR_SANDBOX_SOURCE_DIR to its location")
endif()

# These normal variables apply to the embedded project without changing its cache.
set(SENSOR_BUILD_APP OFF)
set(SENSOR_BUILD_TESTS OFF)
add_subdirectory("${SENSOR_SANDBOX_SOURCE_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/sensor-sandbox" EXCLUDE_FROM_ALL)

add_library(sensor_platform_runner src/MultiSensorRunner.cpp src/RunSession.cpp src/EventTransport.cpp src/Experiment.cpp)
target_include_directories(sensor_platform_runner PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(sensor_platform_runner PUBLIC sensor_core)
set_target_properties(sensor_platform_runner PROPERTIES CXX_EXTENSIONS OFF)

add_library(sensor_platform_recording src/EventRecording.cpp)
target_include_directories(sensor_platform_recording PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(sensor_platform_recording PUBLIC sensor_core)
set_target_properties(sensor_platform_recording PROPERTIES CXX_EXTENSIONS OFF)

add_executable(sensor_platform src/main.cpp)
add_library(sensor_platform_fusion src/Fusion.cpp src/FusionCli.cpp)
target_link_libraries(sensor_platform_fusion PUBLIC sensor_platform_recording)
set_target_properties(sensor_platform_fusion PROPERTIES CXX_EXTENSIONS OFF)
target_link_libraries(sensor_platform PRIVATE sensor_platform_runner sensor_platform_recording sensor_platform_fusion)
set_target_properties(sensor_platform PROPERTIES CXX_EXTENSIONS OFF)

option(SENSOR_PLATFORM_KAFKA "Build the optional Kafka producer/consumer/recorder" OFF)
if(SENSOR_PLATFORM_KAFKA)
    include(cmake/Kafka.cmake)
    add_executable(sensor_platform_kafka src/kafka_main.cpp src/KafkaTransport.cpp)
    target_link_libraries(sensor_platform_kafka PRIVATE sensor_platform_runner sensor_platform_recording RdKafka::rdkafka)
endif()

include(CTest)
option(SENSOR_PLATFORM_VIEWER "Build the optional recording viewer (requires installed raylib)" OFF)
if(SENSOR_PLATFORM_VIEWER OR BUILD_TESTING)
    add_library(sensor_platform_viewer_state src/viewer/ViewerState.cpp)
    target_link_libraries(sensor_platform_viewer_state PUBLIC sensor_platform_fusion)
    set_target_properties(sensor_platform_viewer_state PROPERTIES CXX_EXTENSIONS OFF)
endif()
if(SENSOR_PLATFORM_VIEWER)
    find_package(raylib 5.5 CONFIG REQUIRED)
    add_executable(sensor_platform_viewer src/viewer/main.cpp)
    target_link_libraries(sensor_platform_viewer PRIVATE sensor_platform_viewer_state raylib)
    set_target_properties(sensor_platform_viewer PROPERTIES CXX_EXTENSIONS OFF)
endif()
if(BUILD_TESTING)
    add_executable(sensor_platform_viewer_tests tests/ViewerTests.cpp)
    target_link_libraries(sensor_platform_viewer_tests PRIVATE sensor_platform_viewer_state)
    add_test(NAME platform_viewer_state COMMAND sensor_platform_viewer_tests)
    set_tests_properties(platform_viewer_state PROPERTIES LABELS "platform;unit;viewer")
    add_executable(sensor_platform_fusion_tests tests/FusionTests.cpp)
    target_link_libraries(sensor_platform_fusion_tests PRIVATE sensor_platform_fusion)
    add_test(NAME platform_fusion COMMAND sensor_platform_fusion_tests)
    set_tests_properties(platform_fusion PROPERTIES LABELS "platform;unit;fusion")
    add_executable(sensor_platform_tests tests/MultiSensorRunnerTests.cpp)
    target_link_libraries(sensor_platform_tests PRIVATE sensor_platform_runner)
    add_test(NAME platform_multi_sensor_runner COMMAND sensor_platform_tests)
    add_executable(sensor_platform_event_tests tests/EventRecordingTests.cpp)
    target_link_libraries(sensor_platform_event_tests PRIVATE sensor_platform_runner sensor_platform_recording)
    add_test(NAME platform_events_and_replay COMMAND sensor_platform_event_tests)
    add_test(NAME platform_headless_measurements
        COMMAND "${CMAKE_COMMAND}" "-DPLATFORM_EXE=$<TARGET_FILE:sensor_platform>"
            "-DTEST_DIR=${CMAKE_CURRENT_BINARY_DIR}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/check_output.cmake")
    set_tests_properties(platform_multi_sensor_runner platform_events_and_replay
        PROPERTIES LABELS "platform;unit")
    set_tests_properties(platform_headless_measurements
        PROPERTIES LABELS "platform;integration")
endif()

# Replace vcpkg's PowerShell app-local hook with CMake's binary dependency scan.
include(cmake/RuntimeDependencies.cmake)
sensor_platform_runtime_dependencies()
