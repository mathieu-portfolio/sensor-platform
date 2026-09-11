execute_process(COMMAND "${PLATFORM_EXE}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE error)
if(NOT result STREQUAL "0")
    message(FATAL_ERROR "Platform failed (${result}): ${error}")
endif()
execute_process(COMMAND "${PLATFORM_EXE}" RESULT_VARIABLE repeated_result OUTPUT_VARIABLE repeated)
if(NOT repeated_result STREQUAL "0" OR NOT output STREQUAL repeated)
    message(FATAL_ERROR "Sample run is not deterministic")
endif()
# Check the actual executable's three independent schedules and merged ordering.
string(REGEX MATCHALL "sensor=[0-9]+ scan=[0-9]+ time=[0-9.]+" headers "${output}")
set(expected
    "sensor=1 scan=1 time=0.00"
    "sensor=2 scan=1 time=0.00"
    "sensor=3 scan=1 time=0.00"
    "sensor=3 scan=2 time=0.25"
    "sensor=2 scan=2 time=0.50"
    "sensor=3 scan=3 time=0.50"
    "sensor=3 scan=4 time=0.75"
    "sensor=1 scan=2 time=1.00"
    "sensor=2 scan=3 time=1.00"
    "sensor=3 scan=5 time=1.00")
if(NOT headers STREQUAL expected)
    message(FATAL_ERROR "Unexpected multi-sensor schedules:\n${output}")
endif()
foreach(measurement IN ITEMS
    "sensor=1 detection=2 position=(110.00, 0.00)"
    "sensor=2 detection=3 position=(110.00, 0.00)"
    "sensor=3 detection=1 position=")
    string(FIND "${output}" "${measurement}" found)
    if(found EQUAL -1)
        message(FATAL_ERROR "Missing measurement ${measurement}:\n${output}")
    endif()
endforeach()
