#!/usr/bin/env python3
"""Report local prerequisites as JSON without installing tools or changing settings."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import os
import sys

from ci_config import ROOT, load_config, require_tool4d_host, resolve_tool_pin, tool4d_executable
from build_cli import native_target
from initialize import github_repository


def doctor(root=ROOT, tool4d=None):
    config = load_config(root)
    report = {"schema": 1, "initialized": config["initialized"],
              "repository": config["repository"], "language": config["language"],
              "host": {"system": platform.system(), "machine": platform.machine()},
              "checks": [], "release_ready": False}
    report["resource_targets"] = config.get("resource_targets", ["macos-x64", "macos-arm64", "windows-x64"])
    report["unsupported_backend_platforms"] = config.get("unsupported_backend_platforms", [])
    report["local_development_only"] = platform.system() in report["unsupported_backend_platforms"]
    report["actual_repository"] = github_repository(root)
    if report["actual_repository"] is None and Path(root).resolve() == ROOT:
        report["actual_repository"] = os.environ.get("GITHUB_REPOSITORY")
    if report["actual_repository"] and report["actual_repository"].rsplit("/", 1)[-1] != config["repository"]:
        raise ValueError("actual GitHub repository basename does not match template.json; initialize exact destination")
    try:
        tool_host = require_tool4d_host()
        host_error = None
    except ValueError as error:
        tool_host, host_error = None, str(error)
    url, digest = resolve_tool_pin(root, host=tool_host or "macos-arm64")
    report["tool4d_pin"] = {"url": url, "archive_sha256": digest}
    def check(name, ok, detail):
        report["checks"].append({"name": name, "status": "passed" if ok else "not_run",
                                 "reason": detail})
    check("initialization", config["initialized"], "configure a destination, not the original template")
    check("python", sys.version_info >= (3, 10), sys.version.split()[0])
    try:
        report["native_target"] = native_target()
        check("native_cli_host", True, report["native_target"])
    except ValueError as error:
        check("native_cli_host", False, str(error))
    tools = {"go": ("go",), "rust": ("cargo", "rustc"), "cpp": ("cmake",)}.get(config["language"], ())
    for tool in tools:
        location = shutil.which(tool)
        check(tool, location is not None, location or "missing selected toolchain")
    if config["initialized"]:
        source = Path(root) / "cli"
        check("cli_source", source.is_dir() and not source.is_symlink(), str(source))
        compiler = Path(root) / "tooling/compiler/Project/compiler.4DProject"
        check("compiler_driver", compiler.is_file(), str(compiler))
    artifact_paths = ["build/compile-status.json", "build/source-host-status.json",
                      "build/compiled-host-status.json", f"dist/{config['repository']}.zip"]
    if report["local_development_only"]:
        artifact_paths.extend((f"dist/development/{config['repository']}.zip",
                               f"dist/development/{config['repository']}.acceptance.json"))
    report["artifacts"] = [
        {"path": str(Path(root) / relative),
         "status": "present" if (Path(root) / relative).is_file() else "not_run"}
        for relative in artifact_paths]
    check("pinned_tool4d_host", tool_host is not None, tool_host or host_error)
    candidate = Path(tool4d) if tool4d else tool4d_executable(root, tool_host or "macos-arm64")
    check("tool4d", candidate.is_file() and os.access(candidate, os.X_OK), str(candidate))
    if platform.system() == "Darwin" and {"macos-x64", "macos-arm64"} <= set(report["resource_targets"]):
        check("lipo", shutil.which("lipo") is not None, "required for universal resource assembly")
    report["ready_for_local_acceptance"] = all(entry["status"] == "passed" for entry in report["checks"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tool4d", type=Path)
    args = parser.parse_args()
    try:
        report = doctor(args.root, args.tool4d)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"schema": 1, "error": str(error), "release_ready": False}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report["ready_for_local_acceptance"] else 2


if __name__ == "__main__":
    sys.exit(main())
