# Windows needs dependent DLLs beside executables. Other platforms retain their
# normal loader/RPATH behavior. No Python or package-manager executable is needed.
function(sensor_platform_runtime_dependencies)
    if(NOT WIN32)
        return()
    endif()

    set(search_dirs)
    get_property(imports DIRECTORY PROPERTY IMPORTED_TARGETS)
    foreach(target IN LISTS imports)
        get_target_property(configs "${target}" IMPORTED_CONFIGURATIONS)
        set(properties IMPORTED_LOCATION IMPORTED_IMPLIB)
        foreach(config IN LISTS configs)
            string(TOUPPER "${config}" config)
            list(APPEND properties "IMPORTED_LOCATION_${config}" "IMPORTED_IMPLIB_${config}")
        endforeach()
        foreach(property IN LISTS properties)
            get_target_property(location "${target}" "${property}")
            if(location)
                get_filename_component(directory "${location}" DIRECTORY)
                # Some packages (including raylib) expose only the import .lib.
                if(property MATCHES "^IMPORTED_(LOCATION|IMPLIB)_(.+)$")
                    list(APPEND search_dirs
                        "$<$<CONFIG:${CMAKE_MATCH_2}>:${directory}>"
                        "$<$<CONFIG:${CMAKE_MATCH_2}>:${directory}/../bin>")
                else()
                    list(APPEND search_dirs "${directory}" "${directory}/../bin")
                endif()
            endif()
        endforeach()
    endforeach()
    if(VCPKG_INSTALLED_DIR AND VCPKG_TARGET_TRIPLET)
        list(PREPEND search_dirs
            "${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/$<$<CONFIG:Debug>:debug/>bin")
    endif()
    list(REMOVE_DUPLICATES search_dirs)
    # Keep the configured binary inspection tool available in script mode.
    if(MSVC)
        get_filename_component(tool_dir "${CMAKE_LINKER}" DIRECTORY)
        set(scan_tool "${tool_dir}/dumpbin.exe")
        set(scan_kind dumpbin)
    else()
        set(scan_tool "${CMAKE_OBJDUMP}")
        set(scan_kind objdump)
    endif()
    get_property(targets DIRECTORY PROPERTY BUILDSYSTEM_TARGETS)
    foreach(target IN LISTS targets)
        get_target_property(type "${target}" TYPE)
        if(type STREQUAL "EXECUTABLE")
            add_custom_command(TARGET "${target}" POST_BUILD
                COMMAND "${CMAKE_COMMAND}"
                    "-DEXECUTABLE=$<TARGET_FILE:${target}>"
                    "-DSEARCH_DIRS=${search_dirs}"
                    "-DCMAKE_GET_RUNTIME_DEPENDENCIES_COMMAND=${scan_tool}"
                    "-DCMAKE_GET_RUNTIME_DEPENDENCIES_TOOL=${scan_kind}"
                    -P "${CMAKE_CURRENT_FUNCTION_LIST_DIR}/CopyRuntimeDependencies.cmake"
                VERBATIM)
        endif()
    endforeach()
endfunction()
