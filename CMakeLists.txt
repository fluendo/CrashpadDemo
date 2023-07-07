cmake_minimum_required(VERSION 3.22.3-3.23)

# Project definition
project(
    crashpaddemo
    VERSION 0.1
    DESCRIPTION "Sample project that showcases how to integrate Crashpad in your C/C++ application"
    LANGUAGES CXX)

list(APPEND CMAKE_MODULE_PATH ${CMAKE_BINARY_DIR})
list(APPEND CMAKE_PREFIX_PATH ${CMAKE_BINARY_DIR})

# Find Crashpad with conan
if(NOT EXISTS "${CMAKE_BINARY_DIR}/conan.cmake")
  message(STATUS "Downloading conan.cmake from https://github.com/conan-io/cmake-conan")
  file(DOWNLOAD "https://raw.githubusercontent.com/conan-io/cmake-conan/0.18.1/conan.cmake"
                "${CMAKE_BINARY_DIR}/conan.cmake"
                TLS_VERIFY ON)
endif()
include(${CMAKE_BINARY_DIR}/conan.cmake)
conan_cmake_configure(REQUIRES crashpad/cci.20220219
                      GENERATORS cmake_find_package)
conan_cmake_autodetect(settings)
conan_cmake_install(PATH_OR_REFERENCE .
                    BUILD missing
                    REMOTE conancenter
                    SETTINGS ${settings})
find_package(crashpad)


# Create the crashpaddemo binary linking to crashpad
add_executable(crashpaddemo demo.cpp)
set_property(TARGET crashpaddemo PROPERTY CXX_STANDARD 17)
target_link_libraries(crashpaddemo crashpad::client)

# Add CRASHPAD_HANDLER_NAME and CRASHPAD_HANDLER_DIR compiler defines
# to locate the crashpad_handler executable in the application
if (WIN32)
set(CRASHPAD_HANDLER crashpad_handler.exe)
else()
set(CRASHPAD_HANDLER crashpad_handler)
endif()
add_compile_definitions(CRASHPAD_HANDLER_NAME=\"${CRASHPAD_HANDLER}\")
add_compile_definitions(CRASHPAD_HANDLER_DIR=\"${CMAKE_BINARY_DIR}\")


# Copy the crashpad_handler binary to the output dirtectory
file(COPY "${crashpad_LIB_DIRS}/../bin/${CRASHPAD_HANDLER}" DESTINATION "${CMAKE_BINARY_DIR}")

# Generate symbols generate_symbols.py
find_package(Python3 "3.8" QUIET REQUIRED COMPONENTS Interpreter)
add_custom_command(
    TARGET crashpaddemo
    POST_BUILD
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/generate_symbols.py ${CMAKE_BINARY_DIR}/crashpaddemo${CMAKE_EXECUTABLE_SUFFIX}
            ${CMAKE_BINARY_DIR}/syms --verbose -d ${DUMP_SYMS}
    COMMENT "Generating symbols for CrashPad")