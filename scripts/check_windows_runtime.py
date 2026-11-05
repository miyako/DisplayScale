#!/usr/bin/env python3
"""Inspect native MSVC Release runtime selection and the exact executable's imports."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import xml.etree.ElementTree as ET

from build_cli import native_target
from build_provenance import sha256, verify
from ci_config import ROOT, load_config


SYSTEM_IMPORTS = {"kernel32.dll", "user32.dll", "shcore.dll"}
DYNAMIC_OR_DEBUG_LIBRARIES = {
    "msvcrt", "msvcrtd", "msvcprt", "msvcprtd", "libcmtd", "libcpmtd",
    "ucrt", "ucrtd", "vcruntime", "vcruntimed",
}


def runtime_selection(project):
    if any(path.is_symlink() for path in (project, *project.parents)):
        raise ValueError("generated runtime project must not traverse symlinks")
    document = ET.parse(project)
    selections = []
    for group in document.findall(".//{*}ItemDefinitionGroup"):
        condition = re.sub(r"\s+", "", group.get("Condition", ""))
        if condition == "'$(Configuration)|$(Platform)'=='Release|x64'":
            value = group.find("{*}ClCompile/{*}RuntimeLibrary")
            if value is not None:
                selections.append(value.text)
    if not selections or any(value != "MultiThreaded" for value in selections):
        raise ValueError("Release|x64 must explicitly select MultiThreaded (/MT), not DLL/debug CRT")
    return "MultiThreaded"


def dependency_names(output):
    names = set()
    collecting = False
    found_section = False
    found_summary = False
    for line in output.splitlines():
        if re.fullmatch(r"\s*Image has the following(?: delay load)? dependencies:\s*", line):
            collecting = found_section = True
        elif re.fullmatch(r"\s*Summary\s*", line):
            collecting = False
            found_summary = True
        elif collecting and line.strip():
            match = re.fullmatch(r"\s*([A-Za-z0-9_.-]+\.dll)\s*", line, flags=re.IGNORECASE)
            if not match:
                raise ValueError("unrecognized dumpbin dependency line: " + line.strip())
            names.add(match[1].lower())
    if not found_section or not found_summary or not names:
        raise ValueError("dumpbin did not provide a complete nonempty dependency section")
    unexpected = names - SYSTEM_IMPORTS
    if unexpected:
        raise ValueError("unexpected non-allowlisted DLL imports: " + ", ".join(sorted(unexpected)))
    if not SYSTEM_IMPORTS <= names:
        raise ValueError("expected Windows system API imports are missing")
    return sorted(names)


def default_libraries(output):
    libraries = {
        PureWindowsPath(quoted or plain).name.lower().removesuffix(".lib")
        for quoted, plain in re.findall(
            r'/DEFAULTLIB:(?:"([^"]+)"|([^\s]+))', output, flags=re.IGNORECASE)
    }
    if "libcmt" not in libraries or libraries & DYNAMIC_OR_DEBUG_LIBRARIES:
        raise ValueError("compiled object directives must select retail static LIBCMT, not DLL/debug CRT")
    return sorted(libraries)


def dumpbin_path(cmake):
    configurations = list((cmake / "CMakeFiles").glob("*/CMakeCXXCompiler.cmake"))
    if len(configurations) != 1:
        raise ValueError("exactly one generated CMake C++ compiler configuration is required")
    if any(path.is_symlink() for path in (configurations[0], *configurations[0].parents)):
        raise ValueError("generated compiler configuration must not traverse symlinks")
    text = configurations[0].read_text(encoding="utf-8")
    match = re.search(r'^set\(CMAKE_CXX_COMPILER "([^"]+)"\)', text, flags=re.MULTILINE)
    if not match:
        raise ValueError("generated CMake configuration does not identify the actual compiler")
    compiler = Path(match[1])
    tool = compiler.with_name("dumpbin.exe")
    if not compiler.is_absolute() or not compiler.is_file() or not tool.is_file():
        raise ValueError("the configured MSVC compiler and sibling dumpbin.exe are required")
    return tool


def inspect(root):
    root = Path(root).resolve()
    if native_target() != "windows-x64":
        raise ValueError("runtime inspection requires native Windows x64, not cross/translated execution")
    config = load_config(root, initialized=True, repository=os.environ.get("GITHUB_REPOSITORY"))
    if config["language"] != "cpp":
        raise ValueError("MSVC runtime inspection requires the selected C++ implementation")
    output = root / "build/windows-x64"
    executable = output / (config["cli"] + ".exe")
    manifest = verify(root, "windows-x64", executable)
    if manifest.get("execution") != "passed" or not manifest.get("toolchain", "").startswith("MSVC "):
        raise ValueError("same-revision native MSVC execution evidence is required")
    cmake = output / "cmake"
    selection = runtime_selection(cmake / (config["cli"] + ".vcxproj"))
    tool = dumpbin_path(cmake)
    objects = sorted((cmake / (config["cli"] + ".dir") / "Release").rglob("*.obj"))
    if not objects:
        raise ValueError("compiled production Release object files are required")
    environment = dict(os.environ, VSLANG="1033")

    def run(arguments):
        return subprocess.run([str(tool), *arguments], check=True, capture_output=True,
                              text=True, encoding="utf-8", env=environment, timeout=30).stdout

    dependencies = run(["/DEPENDENTS", str(executable)])
    imports = dependency_names(dependencies)
    directives = {}
    object_evidence = []
    for path in objects:
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("compiled production objects must not traverse symlinks")
        relative = path.relative_to(root).as_posix()
        text = run(["/DIRECTIVES", str(path)])
        libraries = default_libraries(text)
        directives[relative] = text
        object_evidence.append({"path": relative, "sha256": sha256(path),
                                "default_libraries": libraries})
    if verify(root, "windows-x64", executable) != manifest:
        raise ValueError("native artifact or source provenance changed during inspection")
    for name in ("runtime-imports.txt", "runtime-directives.json", "runtime-status.json"):
        path = output / name
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError("runtime evidence output must not traverse symlinks")
    (output / "runtime-imports.txt").write_text(dependencies, encoding="utf-8")
    (output / "runtime-directives.json").write_text(json.dumps(directives, indent=2) + "\n", encoding="utf-8")
    return {
        "schema": 1, "status": "passed", "success": True, "finished": True,
        "target": "windows-x64", "commit": manifest["commit"],
        "source_sha256": manifest["source_sha256"], "binary_sha256": manifest["binary_sha256"],
        "toolchain": manifest["toolchain"], "inspection": "native MSVC dumpbin",
        "runtime": {"configuration": "Release|x64", "msvc_runtime_library": selection,
                    "compiler_switch": "/MT", "objects": object_evidence},
        "imports": imports, "dumpbin_sha256": sha256(tool),
        "imports_output_sha256": hashlib.sha256(dependencies.encode("utf-8")).hexdigest(),
        "bundled_runtime_dlls": [],
        "clean_machine_run": {"status": "not_run", "reason": "hosted runner has installed developer tools"},
        "limitations": "Direct/delay DLL imports and compiled CRT selection, not clean-machine or transitive OS DLL execution",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    arguments = parser.parse_args()
    destination = arguments.root.resolve() / "build/windows-x64/runtime-status.json"
    try:
        report = inspect(arguments.root)
    except (ValueError, OSError, ET.ParseError, UnicodeError, subprocess.SubprocessError) as error:
        report = {"schema": 1, "status": "failed", "success": False, "finished": False,
                  "error": str(error), "clean_machine_run": {"status": "not_run"}}
        print(json.dumps(report, indent=2))
        if destination.parent.is_dir() and not any(
                path.is_symlink() for path in (destination, *destination.parents)):
            destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return 2
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
