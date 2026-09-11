execute_process(COMMAND "${PLATFORM_EXE}" RESULT_VARIABLE result OUTPUT_VARIABLE live ERROR_VARIABLE error)
if(NOT result STREQUAL "0")
    message(FATAL_ERROR "Live sample failed: ${error}")
endif()
set(recording "${TEST_DIR}/sample-test.events")
execute_process(COMMAND "${PLATFORM_EXE}" run --record "${recording}"
    RESULT_VARIABLE result OUTPUT_VARIABLE recorded ERROR_VARIABLE error)
if(NOT result STREQUAL "0")
    message(FATAL_ERROR "Recording failed: ${error}")
endif()
execute_process(COMMAND "${PLATFORM_EXE}" replay "${recording}"
    RESULT_VARIABLE result OUTPUT_VARIABLE replayed ERROR_VARIABLE error)
if(NOT result STREQUAL "0")
    message(FATAL_ERROR "Replay failed: ${error}")
endif()
file(READ "${recording}" saved)
foreach(name IN ITEMS live recorded replayed saved)
    string(REPLACE "\r\n" "\n" ${name} "${${name}}")
endforeach()
if(NOT live STREQUAL recorded OR NOT recorded STREQUAL replayed OR NOT saved STREQUAL replayed)
    message(FATAL_ERROR "Live, saved and replayed streams differ")
endif()
string(REGEX MATCHALL "MEASUREMENTS [^\n]+" scans "${live}")
list(LENGTH scans count)
if(NOT count EQUAL 10)
    message(FATAL_ERROR "Expected ten scans across three radars")
endif()
foreach(expected IN ITEMS
    "MEASUREMENTS 1 0 5 0 1 0 1 1"
    "MEASUREMENTS 1 0 6 0 2 0 1 1"
    "MEASUREMENTS 1 0 7 0 3 0 1"
    "MEASUREMENTS 1 0 12 1 1 0 2 1"
    "MEASUREMENTS 1 0 13 1 2 0 3 1"
    "MEASUREMENTS 1 0 14 1 3 0 5"
    "RUN_FINISHED 1 0 15 1")
    string(FIND "${live}" "${expected}" found)
    if(found EQUAL -1)
        message(FATAL_ERROR "Missing expected event: ${expected}\n${live}")
    endif()
endforeach()

# A line-boundary truncation must fail without emitting any partial observable stream.
string(REGEX REPLACE "RUN_FINISHED[^\n]*\n" "" truncated "${saved}")
file(WRITE "${TEST_DIR}/truncated-test.events" "${truncated}")
execute_process(COMMAND "${PLATFORM_EXE}" replay "${TEST_DIR}/truncated-test.events"
    RESULT_VARIABLE result OUTPUT_VARIABLE partial ERROR_VARIABLE error)
if(result STREQUAL "0" OR NOT partial STREQUAL "" OR NOT error MATCHES "missing RUN_FINISHED")
    message(FATAL_ERROR "Truncated recording did not fail cleanly: ${error}")
endif()
