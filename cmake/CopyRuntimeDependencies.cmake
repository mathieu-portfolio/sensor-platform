set(CMAKE_GET_RUNTIME_DEPENDENCIES_PLATFORM windows+pe)
file(GET_RUNTIME_DEPENDENCIES
    EXECUTABLES "${EXECUTABLE}"
    DIRECTORIES ${SEARCH_DIRS}
    RESOLVED_DEPENDENCIES_VAR dependencies
    PRE_EXCLUDE_REGEXES "api-ms-.*" "ext-ms-.*"
    POST_EXCLUDE_REGEXES ".*[\\/]([Ss][Yy][Ss][Tt][Ee][Mm]32|[Ss][Yy][Ss][Ww][Oo][Ww]64)[\\/].*")
get_filename_component(destination "${EXECUTABLE}" DIRECTORY)
foreach(dependency IN LISTS dependencies)
    get_filename_component(source_dir "${dependency}" DIRECTORY)
    if(NOT source_dir STREQUAL destination)
        execute_process(COMMAND "${CMAKE_COMMAND}" -E copy_if_different
            "${dependency}" "${destination}" COMMAND_ERROR_IS_FATAL ANY)
    endif()
endforeach()
