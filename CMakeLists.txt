cmake_minimum_required(VERSION 3.20)
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

add_library(sensor_platform_runner src/MultiSensorRunner.cpp)
target_include_directories(sensor_platform_runner PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/src")
target_link_libraries(sensor_platform_runner PUBLIC sensor_core)
set_target_properties(sensor_platform_runner PROPERTIES CXX_EXTENSIONS OFF)

add_executable(sensor_platform src/main.cpp)
target_link_libraries(sensor_platform PRIVATE sensor_platform_runner)
set_target_properties(sensor_platform PROPERTIES CXX_EXTENSIONS OFF)

include(CTest)
if(BUILD_TESTING)
    add_executable(sensor_platform_tests tests/MultiSensorRunnerTests.cpp)
    target_link_libraries(sensor_platform_tests PRIVATE sensor_platform_runner)
    add_test(NAME platform_multi_sensor_runner COMMAND sensor_platform_tests)
    add_test(NAME platform_headless_measurements
        COMMAND "${CMAKE_COMMAND}" "-DPLATFORM_EXE=$<TARGET_FILE:sensor_platform>"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/tests/check_output.cmake")
endif()
