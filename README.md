
# Background

Software crashes are an unfortunate reality, whether due to bugs or incompatibilities with other software. Fixing these issues in any software running in the client can be quite challenging: user reports and manual reproduction can help, but often the problem is hard to replicate or poorly reported. To alleviate this, automatic crash telemetry has emerged as a reliable solution, consisting in capturing crash dumps when a crash occurs and sending them to a server for analysis.

Postmortem crash dumps need to capture the program state at the time of the crash with sufficient detail for diagnosis and resolution. However, transmitting the entire program state to the server is usually impractical due to its size or missing information due to missing debug symbols in release builds. Turning these crash dumps thread backtraces into readable function names and line numbers in source code involves 2 processes called stackwalwing and symbolication.

In this blog post, we explore the benefits and challenges of automatic crash telemetry using Crashpad for C/C++ projects, explaining how to integrate Crashpad in your application, generate crash dumps from release builds and convert them into fully symbolicated backtraces.

# What is Crashpad?

Crashpad is an open-source multiplatform crash reporting system written in C++ by Google, capable of capturing and transmitting postmortem crash reports to a backend server. It's the successor of Breakpad and reuses the same symbols format. It consists of two components: the handler and the client, and set of utilities to generate symbols in the Breakpad format and to process minidumps with backtraces and symbolication

## Crashpad Handler

The handler operates in a separate process from the client and is responsible for snapshoting the crashed client process, generating crash dumps, and transmitting them to an upstream server. Clients register with the handler, allowing it to capture and upload their crashes. The Crashpad handler is instantiated within the embedding application's process. When a crash occurs, the handler captures the state of the crashed client process, saves it as a postmortem dump in a database, and potentially transmits the dump to an upstream server based on configuration.

## Crashpad Client

The Crashpad client offers two primary functionalities. Firstly, it facilitates registration with the Crashpad handler, allowing client processes to establish a connection. Secondly, it enables metadata communication to the handler when a crash occurs. Each client module that links the Crashpad client library embeds a CrashpadInfo structure, which can be updated by the client with relevant state information to be recorded alongside the crash.

## dump_syms

<https://crates.io/crates/dump_syms>
dump_syms is a command-line utility for parsing the debugging information the compiler provides (whether as DWARF or STABS sections in an ELF file or as stand-alone PDB files) and writing that information back out in the Breakpad symbol file format.

## minidump-stackwalk

A CLI frontend for minidump-processor, providing both machine-readable and human-readable digests of a minidump, with backtraces and symbolication.
<https://crates.io/crates/minidump-stackwalk>

# Integrate Crashpad in your application

## Overview of the CMake Script

Let's break down the provided CMake script step by step to understand its purpose and how it facilitates the integration of Crashpad into a C/C++ application.

### Setting Minimum CMake Version

```cmake
cmake_minimum_required(VERSION 3.22.3-3.23)
```

This line specifies the minimum required version of CMake for this script to run. In this case, the script requires at least CMake version 3.22.3.

### Project Definition

```cmake
project(
    crashpaddemo
    VERSION 0.1
    DESCRIPTION "Sample project that showcases how to integrate Crashpad in your C/C++ application"
    LANGUAGES CXX)
```

Here, we define the project named "crashpaddemo" with version 0.1. Additionally, we provide a brief description of the project and specify that it will be using the C++ programming language.

### Find Crashpad with conan

```cmake
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
```

This section handles the integration of Crashpad using Conan, a C/C++ package manager. It downloads the conan.cmake script if it doesn't exist, configures Conan to use Crashpad version cci.20220219, and installs Crashpad using Conan. Finally, it finds the installed Crashpad package.

### Building the Application

```cmake
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
```

This section creates the executable crashpaddemo, links it with the Crashpad client library, and sets the C++ standard to C++17. Additionally, it defines compiler variables for the crashpad_handler executable name and its directory based on the operating system.

### Post-Build Actions

```cmake
# Generate symbols using generate_symbols.py
find_package(Python3 "3.8" QUIET REQUIRED COMPONENTS Interpreter)
add_custom_command(
    TARGET crashpaddemo
    POST_BUILD
    COMMAND ${Python3_EXECUTABLE} ${CMAKE_SOURCE_DIR}/generate_symbols.py ${CMAKE_BINARY_DIR}/crashpaddemo${CMAKE_EXECUTABLE_SUFFIX}
            ${CMAKE_BINARY_DIR}/syms --verbose -d ${DUMP_SYMS}
    COMMENT "Generating symbols for CrashPad")
```

This section sets up a post-build command to run a Python script (generate_symbols.py) to generate symbols for CrashPad. This is essential for analyzing crash reports effectively.

# Symbols generation

dump_syms is a command-line utility for parsing the debugging information the compiler provides (whether as DWARF or STABS sections in an ELF file or as stand-alone PDB files) and writing that information back out in the Breakpad symbol file format.

<https://github.com/mozilla/dump_syms>

# Analyzing minidumps

# Resources

[0] <https://chromium.googlesource.com/crashpad/crashpad/+/HEAD/doc/overview_design.md>
[1] <https://chromium.googlesource.com/crashpad/crashpad/+/HEAD/doc/overview_design.md>
[2] <https://docs.sentry.io/platforms/native/guides/crashpad/>
