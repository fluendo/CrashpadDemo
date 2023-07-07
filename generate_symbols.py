#!/usr/bin/env python3
# Copyright 2013 The Chromium Authors
# Copyright 2023 Fluendo S.A.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A tool to generate symbols for a binary suitable for breakpad.
Currently, the tool only supports Linux, Android, and Mac. Support for other
platforms is planned.
"""
import collections
import errno
import glob
import multiprocessing
from pathlib import Path
import optparse
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import traceback


CONCURRENT_TASKS = multiprocessing.cpu_count()
if sys.platform == "win32":
    # TODO(crbug.com/1190269) - we can't use more than 56
    # cores on Windows or Python3 may hang.
    CONCURRENT_TASKS = min(CONCURRENT_TASKS, 56)
    DUMP_SYMS = "dump_syms.exe"
else:
    DUMP_SYMS = "dump_syms"

# The BINARY_INFO tuple describes a binary as dump_syms identifies it.
BINARY_INFO = collections.namedtuple("BINARY_INFO", ["platform", "arch", "hash", "name"])


def get_dump_syms_binary(dump_syms_path: str = None):
    """Returns the path to the dump_syms binary."""
    if dump_syms_path is None:
        dump_syms_path = Path(DUMP_SYMS)
    else:
        dump_syms_path = Path(dump_syms_path)
        if not dump_syms_path.exists():
            print("Cannot find %s." % dump_syms_path)
            exit(1)
    return dump_syms_path


def resolve(path, exe_path, loader_path, rpaths):
    """Resolve a dyld path.
    @executable_path is replaced with |exe_path|
    @loader_path is replaced with |loader_path|
    @rpath is replaced with the first path in |rpaths| where the referenced file
        is found
    """
    path = path.replace("@loader_path", str(loader_path))
    path = path.replace("@executable_path", str(exe_path))
    if path.find("@rpath") != -1:
        for rpath in rpaths:
            new_path = path.replace("@rpath", rpath)
            if os.access(new_path, os.X_OK):
                return new_path
        return ""
    return path


def get_developer_dir_mac():
    """Finds a good DEVELOPER_DIR value to run Mac dev tools.
    It checks the existing DEVELOPER_DIR and `xcode-select -p` and uses
    one of those if the folder exists, and falls back to one of the
    existing system folders with dev tools.
    Returns:
      (string) path to assign to DEVELOPER_DIR env var.
    """
    candidate_paths = []
    if "DEVELOPER_DIR" in os.environ:
        candidate_paths.append(os.environ["DEVELOPER_DIR"])
    candidate_paths.extend(
        [
            subprocess.check_output(["xcode-select", "-p"]).decode("utf-8").strip(),
            # Most Mac 10.1[0-2] bots have at least one Xcode installed.
            "/Applications/Xcode.app",
            "/Applications/Xcode9.0.app",
            "/Applications/Xcode8.0.app",
            # Mac 10.13 bots don't have any Xcode installed, but have CLI tools as a
            # temporary workaround.
            "/Library/Developer/CommandLineTools",
        ]
    )
    for path in candidate_paths:
        if Path(path).exists():
            return path
    print("WARNING: no value found for DEVELOPER_DIR. Some commands may fail.")


def get_shared_library_dependenciesMac(binary, exe_path):
    """Return absolute paths to all shared library dependencies of the binary.
    This implementation assumes that we're running on a Mac system."""
    # realpath() serves two purposes:
    # 1. If an executable is linked against a framework, it links against
    #    Framework.framework/Framework, which is a symlink to
    #    Framework.framework/Framework/Versions/A/Framework. rpaths are relative
    #    to the real location, so resolving the symlink is important.
    # 2. It converts binary to an absolute path. If binary is just
    #    "foo.dylib" in the current directory, dirname() would return an empty
    #    string, causing "@loader_path/foo" to incorrectly expand to "/foo".
    loader_path = binary.parent.resolve()
    env = os.environ.copy()
    otool = subprocess.check_output(['otool', "-lm", binary], env=env).decode("utf-8").splitlines()
    rpaths = []
    dylib_id = None
    for idx, line in enumerate(otool):
        if line.find("cmd LC_RPATH") != -1:
            m = re.match(" *path (.*) \(offset .*\)$", otool[idx + 2])
            rpath = m.group(1)
            rpath = rpath.replace("@loader_path", str(loader_path))
            rpath = rpath.replace("@executable_path", str(exe_path))
            rpaths.append(rpath)
        elif line.find("cmd LC_ID_DYLIB") != -1:
            m = re.match(" *name (.*) \(offset .*\)$", otool[idx + 2])
            dylib_id = m.group(1)
    # `man dyld` says that @rpath is resolved against a stack of LC_RPATHs from
    # all executable images leading to the load of the current module. This is
    # intentionally not implemented here, since we require that every .dylib
    # contains all the rpaths it needs on its own, without relying on rpaths of
    # the loading executables.
    otool = subprocess.check_output(['otool', "-Lm", binary], env=env).decode("utf-8").splitlines()
    lib_re = re.compile("\t(.*) \(compatibility .*\)$")
    deps = []
    for line in otool:
        m = lib_re.match(line)
        if m:
            # For frameworks and shared libraries, `otool -L` prints the LC_ID_DYLIB
            # as the first line. Filter that out.
            if m.group(1) == dylib_id:
                continue
            dep = resolve(m.group(1), exe_path, loader_path, rpaths)
            if dep:
                deps.append(os.path.normpath(dep))
            else:
                print(
                    (
                        "ERROR: failed to resolve %s, exe_path %s, loader_path %s, "
                        "rpaths %s" % (m.group(1), exe_path, loader_path, ", ".join(rpaths))
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
    return deps


def get_shared_library_dependenciesLinux(binary):
    """Return absolute paths to all shared library dependencies of the binary.
    This implementation assumes that we're running on a Linux system."""
    ldd = subprocess.check_output(["ldd", binary]).decode("utf-8")
    lib_re = re.compile("\t.* => (.+) \(.*\)$")
    result = []
    for line in ldd.splitlines():
        m = lib_re.match(line)
        if m:
            result.append(os.path.abspath(m.group(1)))
    return result


def get_shared_library_dependenciesWindows(binary: Path):
    cmd = ["dumpbin", "/DEPENDENTS", binary]
    files = subprocess.run(cmd, capture_output=True).stdout.decode("utf-8")
    pattern = r"(\w+\.dll)"
    dll_names = re.findall(pattern, files)
    dll_files = []
    for dll_name in dll_names:
        for path_dir in os.environ["PATH"].split(";") + [Path(binary).parent]:
            dll_file = Path(path_dir) / dll_name
            if dll_file.exists():
                dll_files.append(dll_file)
    return [p.resolve() for p in dll_files]


def get_shared_library_dependencies(binary: Path, exe_path: Path, platform: str):
    """Return absolute paths to all shared library dependencies of the binary."""
    deps = []
    if platform == "linux":
        deps = get_shared_library_dependenciesLinux(binary)
    elif platform == "darwin":
        deps = get_shared_library_dependenciesMac(binary, exe_path)
    elif platform == "win32":
        deps = get_shared_library_dependenciesWindows(binary)
    else:
        print("Platform not supported.")
        sys.exit(1)
    result = []
    build_dir = exe_path.parent
    for dep in deps:
        dep = Path(dep)
        if dep.exists() and str(dep.parent).startswith(str(build_dir)):
            result.append(dep)
    return result


def get_transitive_dependencies(binary: Path, platform: str):
    """Return absolute paths to the transitive closure of all shared library
    dependencies of the binary, along with the binary itself."""
    exe_path = binary.parent
    if platform == "linux":
        # 'ldd' returns all transitive dependencies for us.
        deps = set(get_shared_library_dependencies(binary, exe_path, platform))
        deps.add(binary)
        return list(deps)
    elif platform in ["darwin", "win32"]:
        binaries = set([binary])
        q = [binary]
        while q:
            deps = get_shared_library_dependencies(q.pop(0), exe_path, platform)
            new_deps = set(deps) - binaries
            binaries |= new_deps
            q.extend(list(new_deps))
        return binaries
    print("Platform not supported.")
    sys.exit(1)


def get_binary_info_from_header_info(header_info):
    """Given a standard symbol header information line, returns BINARY_INFO."""
    # header info is of the form "MODULE $PLATFORM $ARCH $HASH $BINARY"
    info_split = header_info.strip().split(" ", 4)
    if len(info_split) != 5 or info_split[0] != "MODULE":
        return None
    return BINARY_INFO(*info_split[1:])


def create_symbol_dir(output_dir: Path, platform: str, relative_hash_dir):
    """Create the directory to store breakpad symbols in. On Android/Linux, we
    also create a symlink in case the hash in the binary is missing."""
    output_dir.mkdir(parents=True, exist_ok=True)
    if platform == "android" or platform == "linux":
        try:
            os.symlink(
                relative_hash_dir,
                output_dir.parent / "000000000000000000000000000000000",
            )
        except:
            pass


def generate_symbols(
    symbols_dir: Path,
    platform: str,
    dump_syms: Path,
    jobs: int,
    verbose: bool,
    binaries: list,
):
    """Dumps the symbols of binary and places them in the given directory."""
    q = queue.Queue()
    exceptions = []
    print_lock = threading.Lock()
    exceptions_lock = threading.Lock()

    def _Worker():
        while True:
            try:
                should_dump_syms = True
                reason = "no reason"
                binary = q.get()
                run_once = True
                while run_once:
                    run_once = False
                    if not dump_syms:
                        should_dump_syms = False
                        reason = "Could not locate dump_syms executable."
                        break
                    dump_syms_output = subprocess.check_output([dump_syms, binary]).decode("utf-8")
                    header_info = dump_syms_output.splitlines()[0]
                    binary_info = get_binary_info_from_header_info(header_info)
                    if not binary_info:
                        should_dump_syms = False
                        reason = "Could not obtain binary information."
                        break
                    # See if the output file already exists.
                    output_dir = symbols_dir / binary_info.name / binary_info.hash
                    output_path = output_dir / Path(binary_info.name).with_suffix(".sym")
                    if output_path.exists():
                        should_dump_syms = False
                        reason = "Symbol file already found."
                        break
                    # See if there is a symbol file already found next to the binary
                    potential_symbol_files = glob.glob("%s.breakpad*" % binary)
                    for potential_symbol_file in potential_symbol_files:
                        with open(potential_symbol_file, "rt") as f:
                            symbol_info = get_binary_info_from_header_info(f.readline())
                        if symbol_info == binary_info:
                            create_symbol_dir(output_dir, platform, binary_info.hash)
                            shutil.copyfile(potential_symbol_file, output_path)
                            should_dump_syms = False
                            reason = "Found local symbol file."
                            break
                if not should_dump_syms:
                    if verbose:
                        with print_lock:
                            print("Skipping %s (%s)" % (binary, reason))
                    continue
                if verbose:
                    with print_lock:
                        print("Generating symbols for %s" % binary)
                subprocess.check_call([dump_syms, binary, "-s", symbols_dir])
            except Exception as e:
                with exceptions_lock:
                    exceptions.append(traceback.format_exc())
            finally:
                q.task_done()

    for binary in binaries:
        q.put(binary)
    for _ in range(jobs):
        t = threading.Thread(target=_Worker)
        t.daemon = True
        t.start()
    q.join()
    if exceptions:
        exception_str = "One or more exceptions occurred while generating " "symbols:\n"
        exception_str += "\n".join(exceptions)
        raise Exception(exception_str)


def main():
    usage = "usage: %prog [options] binary symbols_dir"
    parser = optparse.OptionParser(usage=usage)
    parser.add_option("-d", "--dump_syms_path", default=None, help="Path to the dump_syms utility.")
    parser.add_option(
        "",
        "--clear",
        default=False,
        action="store_true",
        help="Clear the symbols directory before writing new " "symbols.",
    )
    parser.add_option(
        "-j",
        "--jobs",
        default=CONCURRENT_TASKS,
        action="store",
        type="int",
        help="Number of parallel tasks to run.",
    )
    parser.add_option("-v", "--verbose", action="store_true", help="Print verbose status output.")
    parser.add_option("", "--platform", default=sys.platform, help="Target platform of the binary.")
    (options, args) = parser.parse_args()
    if len(args) != 2:
        parser.print_usage()
        exit(1)
    binary = Path(args[0]).resolve()
    if not binary.exists():
        print("Cannot find %s." % args[0])
        return 1
    symbols_dir = Path(args[1]).resolve()
    if options.clear:
        try:
            shutil.rmtree(symbols_dir)
        except:
            pass
    dump_syms = get_dump_syms_binary(options.dump_syms_path)
    # Build the transitive closure of all dependencies.
    binaries = get_transitive_dependencies(binary, options.platform)
    generate_symbols(
        symbols_dir,
        options.platform,
        dump_syms,
        options.jobs,
        options.verbose,
        binaries,
    )
    return 0


if "__main__" == __name__:
    sys.exit(main())
