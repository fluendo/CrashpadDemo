
# Background

Software crashes are an unfortunate reality, whether due to bugs or incompatibilities with other software. Fixing these issues in any software running in the client can be quite challenging: user reports and manual reproduction can help, but often the problem is hard to replicate or poorly reported. To alleviate this, automatic crash telemetry has emerged as a reliable solution, consisting in capturing crash dumps when a crash occurs and sending them to a server for analysis.

Postmortem crash dumps need to capture the program state at the time of the crash with sufficient detail for diagnosis and resolution. However, transmitting the entire program state to the server is usually impractical due to its size or missing information due to missing debug symbols in release builds. Turning these crash dumps thread backtraces into readable function names and line numbers in source code involves 2 processes called stackwalking and symbolication.

In this repository, we explore the benefits and challenges of automatic crash telemetry using Crashpad for C/C++ projects, explaining how to integrate Crashpad in your application, generate crash dumps from release builds and convert them into fully symbolicated backtraces.

# What is Crashpad?

Crashpad is an open-source multiplatform crash reporting system written in C++ by Google, capable of capturing and transmitting postmortem crash reports to a backend server. It's the successor of Breakpad and reuses the same symbols format. It consists of two components: the handler and the client, and set of utilities to generate symbols in the Breakpad format and to process minidumps with backtraces and symbolication

## Crashpad Handler

The handler operates in a separate process from the client and is responsible for snapshoting the crashed client process, generating crash dumps, and transmitting them to an upstream server. Clients register with the handler, allowing it to capture and upload their crashes. The Crashpad handler is instantiated within the embedding application's process. When a crash occurs, the handler captures the state of the crashed client process, saves it as a postmortem dump in a database, and potentially transmits the dump to an upstream server based on configuration.

## Crashpad Client

The Crashpad client offers two primary functionalities. Firstly, it facilitates registration with the Crashpad handler, allowing client processes to establish a connection. Secondly, it enables metadata communication to the handler when a crash occurs. Each client module that links the Crashpad client library embeds a CrashpadInfo structure, which can be updated by the client with relevant state information to be recorded alongside the crash.

## dump_syms

[dump_syms](https://crates.io/crates/dump_syms) is a command-line utility for parsing the debugging information the compiler provides (whether as DWARF or STABS sections in an ELF file or as stand-alone PDB files) and writing that information back out in the Breakpad symbol file format.

```
cargo install dump_syms
```

## minidump-stackwalk

[minidump-stackwalk](https://crates.io/crates/minidump-stackwalk) is a CLI frontend for minidump-processor, providing both machine-readable and human-readable digests of a minidump, with backtraces and symbolication.

```
cargo install minidump-stackwalk
```

# Integrate Crashpad in your application

## Crashpad initialization and configuration

Crashpad's initialization done through a helper function that requires a path to the Crashpad handler binary and a directory to use for the database.


```cpp
    fs::path db = fs::absolute(fs::path("crashpad_db"));
    fs::create_directory(db);
    fs::path crashpadHandlerPath = fs::path (CRASHPAD_HANDLER_DIR) / CRASHPAD_HANDLER_NAME;

    auto client = init("crashpaddemo", "0.1", crashpadHandlerPath.native(), db.native());

```

## Overview of the CMake Script

Let's break down the provided CMake script step by step to understand its purpose and how it facilitates the integration of Crashpad into a C/C++ application.

### Setting Minimum CMake Version

```cmake
cmake_minimum_required(VERSION 3.22.3-3.23)
```

This line specifies the minimum required version of CMake for this script to run. In this case, the script requires at least CMake version 3.22.3.

### Adding the Crashpad dependency with conan

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

This section creates the executable crashpaddemo and links it with the Crashpad client library. Additionally, it defines compiler variables for the crashpad_handler executable name and its directory to be used by the application.

### Generate debug symbols with a post-build action

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

This section sets up a post-build command that runs the `generate_symbols.py` script to generate symbols of the recently built application for CrashPad.
The `generate-symbols.py` script iterates over all the shared libraries dependencies and uses `dump_syms` to generate the symbol files for all of them.
This is essential for analyzing crash reports effectively since we will need these symbols to desymbolicate our stacktraces and convert memory addresses
to function names.

After the build, the symbols for our application will be generated in the `syms` folder, under a subfolder with a UUID that identifies the binary that was built:

`syms/crashpaddemo/E9F5B8DB43A93CEF90719355360C864E0/crashpaddemo.sym`


# Run the application

The `crashpaddemo` application is designed to segfault. If CrashPad is initialized and configured correctly, it will catch the segfault and generate a minidump.

```bash
✗ ./crashpaddemo
Entering main()
Initializing crashpad handler
Entering function1()
Entering function2()
Entering function3()... BOOM!
[1]    13958 segmentation fault  ./crashpaddemo
```

```powershell
PS D:\Sources\fluendo\CrashpadDemo\build> ls .\crashpad_db\reports\


    Directory: D:\Sources\fluendo\CrashpadDemo\build\crashpad_db\reports


Mode                 LastWriteTime         Length Name
----                 -------------         ------ ----
-a----        21/12/2023     11:44         117648 5495e864-c173-46bd-918d-81479772ea6d.dmp
```

# Analyzing minidumps

After a crash, a minidump is saved in the CrashPad database (using the path we used in CrashPad's initialization).

We will use `minidump-stackwalk` to get a stracktrace of all the threads, using the path our symbols library generated during the build process.
We are now using a local folder to store the symbols or our built application, but symbols can be uploaded to a symbols server to be used
from a different machine.

```powershell
PS D:\Sources\fluendo\CrashpadDemo\build> minidump-stackwalk.exe .\crashpad_db\reports\5495e864-c173-46bd-918d-81479772ea6d.dmp -- .\syms\
Operating system: Windows NT
                  10.0.22621 2861
CPU: amd64
     family 25 model 80 stepping 0
     16 CPUs

Crash reason:  EXCEPTION_ACCESS_VIOLATION_WRITE
Crash address: 0x0000000000000000
Process uptime: 0 seconds

Thread 0  (crashed)
 0  VCRUNTIME140D.dll + 0x1a0e
     rax = 0x0000000000000000    rdx = 0x0000000000000001
     rcx = 0x0000000000000001    rbx = 0x0000000000000000
     rsi = 0x0000000000000000    rdi = 0x0000000000000000
     rbp = 0x0000000000000000    rsp = 0x00000099ae2ff8a8
      r8 = 0x0000000000000001     r9 = 0x00007ff8c0431a0e
     r10 = 0x00007ff8c0430000    r11 = 0x0101010101010101
     r12 = 0x0000000000000000    r13 = 0x0000000000000000
     r14 = 0x0000000000000000    r15 = 0x0000000000000000
     rip = 0x00007ff8c0431a0e
    Found by: given as instruction pointer in context
 1  crashpaddemo.exe!function3() [demo.cpp : 10 + 0x11]
     rsp = 0x00000099ae2ff8b0    rip = 0x00007ff689767a4b
    Found by: stack scanning
 2  crashpaddemo.exe!function2() [demo.cpp : 16 + 0x4]
     rdi = 0x0000000000000000    rsp = 0x00000099ae2ff8e0
     rip = 0x00007ff689767a7e
    Found by: call frame info
 3  crashpaddemo.exe!function1() [demo.cpp : 21 + 0x4]
     rdi = 0x0000000000000000    rsp = 0x00000099ae2ff910
     rip = 0x00007ff689767aae
    Found by: call frame info
 4  crashpaddemo.exe!main() [demo.cpp : 39 + 0x4]
     rdi = 0x0000000000000000    rsp = 0x00000099ae2ff940
     rip = 0x00007ff689767d7a
    Found by: call frame info
 5  crashpaddemo.exe!invoke_main() [exe_common.inl : 78 + 0x34]
     rdi = 0x0000000000000000    rsp = 0x00000099ae2ff980
     rip = 0x00007ff6897e06b9
    Found by: call frame info
 6  crashpaddemo.exe!__scrt_common_main_seh() [exe_common.inl : 288 + 0x4]
     rsp = 0x00000099ae2ff9d0    rip = 0x00007ff6897e055e
    Found by: call frame info
 7  crashpaddemo.exe!__scrt_common_main() [exe_common.inl : 330 + 0x4]
     rsp = 0x00000099ae2ffa40    rip = 0x00007ff6897e041e
    Found by: call frame info
 8  crashpaddemo.exe!mainCRTStartup(void*) [exe_main.cpp : 16 + 0x4]
     rsp = 0x00000099ae2ffa70    rip = 0x00007ff6897e074e
    Found by: call frame info
 9  KERNEL32.DLL + 0x1257c
     rsp = 0x00000099ae2ffaa0    rip = 0x00007ff915b3257d
    Found by: call frame info
10  ntdll.dll + 0x5aa57
     rsp = 0x00000099ae2ffad0    rip = 0x00007ff917e2aa58
    Found by: stack scanning
11  KERNELBASE.dll + 0x15c71f
     rsp = 0x00000099ae2ffb20    rip = 0x00007ff91582c720
    Found by: stack scanning

Thread 1
 0  ntdll.dll + 0xa2fc4
     rax = 0x00000000000001e3    rdx = 0x00000227d52414e0
     rcx = 0x00000000000000ac    rbx = 0x00000227d52420a0
     rsi = 0x0000000000000001    rdi = 0x00000227d5241860
     rbp = 0x0000000000000000    rsp = 0x00000099ae3ffaf8
      r8 = 0x0000000000000000     r9 = 0x00000000000000b6
     r10 = 0x00000000000009f2    r11 = 0x00000000000000b6
     r12 = 0x0000000000000000    r13 = 0x0000000000000000
     r14 = 0x000000000000ffff    r15 = 0x0000000000000000
     rip = 0x00007ff917e72fc4
    Found by: given as instruction pointer in context
 1  ntdll.dll + 0x3537d
     rsp = 0x00000099ae3ffb00    rip = 0x00007ff917e0537e
    Found by: stack scanning
Thread 2
 0  ntdll.dll + 0xa2fc4
     rax = 0x00000000000001e3    rdx = 0x00000227d5245730
     rcx = 0x00000000000000ac    rbx = 0x00000227d52420a0
     rsi = 0x0000000000000001    rdi = 0x00000227d5245ab0
     rbp = 0x0000000000000000    rsp = 0x00000099ae4ff778
      r8 = 0x0000000000000000     r9 = 0x0000000000000446
     r10 = 0x00000000000005f2    r11 = 0x0000000000000446
     r12 = 0x0000000000000000    r13 = 0x0000000000000000
     r14 = 0x000000000000ffff    r15 = 0x0000000000000000
     rip = 0x00007ff917e72fc4
    Found by: given as instruction pointer in context
 1  ntdll.dll + 0x3537d
     rsp = 0x00000099ae4ff780    rip = 0x00007ff917e0537e
    Found by: stack scanning
Thread 3
 0  ntdll.dll + 0xa2fc4
     rax = 0x00000000000001e3    rdx = 0x00000227d5246290
     rcx = 0x00000000000000ac    rbx = 0x00000227d52420a0
     rsi = 0x0000000000000001    rdi = 0x00000227d5246610
     rbp = 0x0000000000000000    rsp = 0x00000099ae5ff948
      r8 = 0x0000000000000005     r9 = 0x00000000000000a2
     r10 = 0x0000000000000140    r11 = 0x00000000000000a2
     r12 = 0x0000000000000000    r13 = 0x0000000000000000
     r14 = 0x000000000000ffff    r15 = 0x0000000000000000
     rip = 0x00007ff917e72fc4
    Found by: given as instruction pointer in context
 1  ntdll.dll + 0x3537d
     rsp = 0x00000099ae5ff950    rip = 0x00007ff917e0537e
    Found by: stack scanning

Loaded modules:
0x7ff689760000 - 0x7ff689828fff  crashpaddemo.exe  0.0.0.0  (main)
0x7ff87eb90000 - 0x7ff87edb0fff  ucrtbased.dll  10.0.22621.1778
0x7ff87f9d0000 - 0x7ff87fab0fff  MSVCP140D.dll  14.36.32532.0
0x7ff8c0430000 - 0x7ff8c045afff  VCRUNTIME140D.dll  14.36.32532.0
0x7ff8e40c0000 - 0x7ff8e40cefff  VCRUNTIME140_1D.dll  14.36.32532.0
0x7ff911fd0000 - 0x7ff912066fff  apphelp.dll  10.0.22621.2506
0x7ff914120000 - 0x7ff914153fff  ntmarta.dll  10.0.22621.1
0x7ff9148a0000 - 0x7ff9148abfff  CRYPTBASE.DLL  10.0.22621.1
0x7ff915140000 - 0x7ff915250fff  ucrtbase.dll  10.0.22621.2506
0x7ff915260000 - 0x7ff9152d9fff  bcryptPrimitives.dll  10.0.22621.2506
0x7ff9156d0000 - 0x7ff915a75fff  KERNELBASE.dll  10.0.22621.2792
0x7ff915b20000 - 0x7ff915be3fff  KERNEL32.DLL  10.0.22621.2506
0x7ff915c50000 - 0x7ff915cf4fff  sechost.dll  10.0.22621.2792
0x7ff916120000 - 0x7ff916236fff  RPCRT4.dll  10.0.22621.2792
0x7ff9164a0000 - 0x7ff916546fff  msvcrt.dll  7.0.22621.2506
0x7ff9172e0000 - 0x7ff917390fff  ADVAPI32.dll  10.0.22621.2792
0x7ff917dd0000 - 0x7ff917fe6fff  ntdll.dll  10.0.22621.2506
```


# Resources

[0] <https://chromium.googlesource.com/crashpad/crashpad/+/HEAD/doc/overview_design.md>

[1] <https://chromium.googlesource.com/crashpad/crashpad/+/HEAD/doc/overview_design.md>

[2] <https://docs.sentry.io/platforms/native/guides/crashpad/>
