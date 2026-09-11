execute_process(COMMAND "${PLATFORM_EXE}" RESULT_VARIABLE result OUTPUT_VARIABLE output ERROR_VARIABLE error)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "Platform failed (${result}): ${error}")
endif()
string(REPLACE "\r\n" "\n" output "${output}")
set(expected "sensor=1 scan=1 time=0.00 measurements=1
  detection=1 position=(100.00, 0.00)
sensor=1 scan=2 time=0.50 measurements=1
  detection=2 position=(105.00, 0.00)
sensor=1 scan=3 time=1.00 measurements=1
  detection=3 position=(110.00, 0.00)
")
if(NOT output STREQUAL expected)
    message(FATAL_ERROR "Unexpected headless measurements:\n${output}\nExpected:\n${expected}")
endif()
