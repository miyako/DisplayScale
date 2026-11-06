#!/usr/bin/env python3
"""Host-test an already built compiled ZIP on the native 4D host, without rebuilding it."""
import argparse
import json
from pathlib import Path
import platform
import sys

from build_provenance import sha256
from ci_config import ROOT, load_config, require_tool4d_host
from package_component import unpack_for_test
from test_4d import test_4d


def accept(root, repository, archive, tool4d):
    root = Path(root).resolve()
    archive = Path(archive).resolve()
    config = load_config(root, initialized=True, repository=repository)
    if (archive.name != config["repository"] + ".zip" or not archive.is_file()
            or any(path.is_symlink() for path in (archive, *archive.parents))):
        raise ValueError("a regular <repository>.zip is required")
    host = require_tool4d_host()
    before = sha256(archive)
    status = test_4d(root, Path(tool4d).resolve(), unpack_for_test(root, archive))
    if sha256(archive) != before:
        raise ValueError("ZIP changed during host acceptance")
    report = {"schema": 1, "scope": "package-host", "host": host,
              "system": platform.system(), "machine": platform.machine(),
              "artifact": {"path": archive.name, "sha256": before}, "compiled_host": status}
    output = root / "build" / ("package-host-" + host + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--tool4d", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = accept(args.root, args.repository, args.zip, args.tool4d)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, f"package host acceptance failed: {error}\n")
    print(json.dumps({"host": report["host"], "artifact": report["artifact"]}, indent=2))


if __name__ == "__main__":
    main()
