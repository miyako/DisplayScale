#!/usr/bin/env python3
"""Validated configuration, native CI matrix, resource assembly and tool4D download."""
import argparse
import hashlib
import json
import os
import platform
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from initialize import validate as validate_initialization


ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("macos-x64", "macos-arm64", "windows-x64")
TOOL4D_DOWNLOAD_HOSTS = {"resources-download.4d.com", "builds2.4d.com"}
SEMVER = r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"


def load_config(root=ROOT, *, initialized=False, repository=None, tag=None):
    config = json.loads((Path(root) / "template.json").read_text(encoding="utf-8"))
    if (not isinstance(config, dict) or type(config.get("schema")) is not int
            or config.get("schema") != 1 or type(config.get("initialized")) is not bool):
        raise ValueError("unsupported template configuration")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", config.get("repository", "")):
        raise ValueError("invalid repository name")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", config.get("cli", "")):
        raise ValueError("invalid CLI name")
    if not re.fullmatch(SEMVER, config.get("version", ""), flags=re.ASCII):
        raise ValueError("version must be SemVer")
    if "resource_targets" in config and config["resource_targets"] != ["windows-x64"]:
        raise ValueError("explicit resource_targets currently supports Windows x64 only")
    if ("unsupported_backend_platforms" in config
            and config["unsupported_backend_platforms"] != ["Darwin"]):
        raise ValueError("unsupported_backend_platforms currently supports Darwin only")
    manifest = json.loads((Path(root) / "package.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("name") != config["repository"]:
        raise ValueError("package.json name must match template.json repository")
    if manifest.get("version") != config["version"]:
        raise ValueError("package.json version must match template.json version")
    if config["initialized"]:
        validate_initialization(
            config["repository"], config.get("namespace", ""), config["cli"],
            config.get("language"), config.get("feature", ""))
        project = Path(root) / "component" / config["repository"] / "Project"
        if not (project / (config["repository"] + ".4DProject")).is_file():
            raise ValueError("configured component .4DProject name/path is missing")
        try:
            settings = ET.parse(project / "Sources" / "settings.4DSettings")
            catalog = ET.parse(project / "Sources" / "catalog.4DCatalog")
        except (ET.ParseError, OSError) as error:
            raise ValueError(f"invalid 4D project metadata: {error}") from error
        general = settings.find(".//general")
        if general is None or general.attrib.get("component_classStore_name") != config["namespace"]:
            raise ValueError("4D project namespace must match template.json")
        if catalog.getroot().attrib.get("name") != config["repository"]:
            raise ValueError("4D catalog name must match template.json repository")
        feature_class = config.get("feature_class", "Greeting")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,30}", feature_class):
            raise ValueError("feature_class must be a non-underscore 4D identifier")
        if not (project / "Sources" / "Classes" / (feature_class + ".4dm")).is_file():
            raise ValueError("configured feature class is missing")
    elif config.get("language") is not None:
        raise ValueError("uninitialized template must not select a language")
    if initialized and not config["initialized"]:
        raise ValueError("initialize the template before building or releasing")
    if repository is not None:
        if not re.fullmatch(r"[^/]+/[^/]+", repository):
            raise ValueError("repository identity must be owner/name")
        if repository.split("/")[1] != config["repository"]:
            raise ValueError("actual repository does not match template.json")
    if tag is not None and tag != config["version"]:
        raise ValueError("release tag must equal template.json version without a v prefix")
    return config


def matrix(config):
    if not config["initialized"]:
        return {"include": []}
    runners = ("macos-15-intel", "macos-15", "windows-2022")
    return {"include": [
        {"target": target, "runner": runner, "language": config["language"]}
        for target, runner in zip(TARGETS, runners)
    ]}


def resource_targets(config, local_development=False):
    if local_development:
        from build_cli import native_target
        if (config.get("resource_targets") != ["windows-x64"]
                or config.get("unsupported_backend_platforms") != ["Darwin"]):
            raise ValueError("local development requires an explicit Windows-only feature and Darwin unsupported backend")
        native = native_target()
        if not native.startswith("macos-"):
            raise ValueError("local development backend is native macOS only")
        return (native,)
    return tuple(config.get("resource_targets", TARGETS))


def assemble(root=ROOT, local_development=False):
    from build_provenance import sha256, verify
    root = Path(root)
    config = load_config(root, initialized=True, repository=os.environ.get("GITHUB_REPOSITORY"))
    destination = root / "component" / config["repository"] / "Resources" / "bin"
    if any(path.is_symlink() for path in [destination, *destination.parents]):
        raise ValueError("resource assembly destination must not traverse symlinks")
    mac = destination / "macOS" / config["cli"]
    windows = destination / "Windows" / (config["cli"] + ".exe")
    targets = resource_targets(config, local_development)
    inputs = [root / "build" / target / (config["cli"] + (".exe" if target == "windows-x64" else ""))
              for target in targets]
    if not all(path.is_file() and not path.is_symlink() for path in inputs):
        raise ValueError("all required native build artifacts are required: " + ", ".join(targets))
    manifests = []
    for target, path in zip(targets, inputs):
        status = verify(root, target, path)
        if status.get("execution") != "passed":
            raise ValueError("production resources require native CLI execution: " + target)
        manifests.append(status)
    if config.get("resource_targets"):
        if destination.exists():
            if any(path.is_symlink() for path in destination.rglob("*")):
                raise ValueError("existing resources must not contain symlinks")
            shutil.rmtree(destination)
        selected = mac if local_development else windows
        selected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(inputs[0], selected)
        selected.chmod(0o755)
        marker = {"schema": 1, "profile": "development" if local_development else "production",
                  "targets": list(targets), "builds": manifests,
                  "resources": {selected.relative_to(destination).as_posix(): sha256(selected)}}
        (destination / "resource-manifest.json").write_text(json.dumps(marker, indent=2) + "\n")
        return destination
    mac.parent.mkdir(parents=True, exist_ok=True)
    windows.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["lipo", "-create", str(inputs[0]), str(inputs[1]), "-output", str(mac)], check=True)
    subprocess.run(["lipo", str(mac), "-verify_arch", "x86_64", "arm64"], check=True)
    mac.chmod(0o755)
    shutil.copyfile(inputs[2], windows)
    windows.chmod(0o755)
    return destination


def tar_mode(archive):
    """4D's Windows tool4d_win.tar.xz is bzip2-compressed; accept only xz or bzip2."""
    with open(archive, "rb") as stream:
        magic = stream.read(6)
    if magic == b"\xfd7zXZ\x00":
        return "r:xz"
    if magic[:3] == b"BZh":
        return "r:bz2"
    raise ValueError("tool4D archive must be ZIP, TAR.XZ or TAR.BZ2")


def extract_tar(archive, tools):
    """Extract regular files first, then validated app-framework symlinks."""
    base = tools.resolve()
    with tarfile.open(archive, tar_mode(archive)) as packed:
        members = packed.getmembers()
        links = {}
        destinations = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (not member.name or path.is_absolute() or ".." in path.parts
                    or "\\" in member.name or ":" in member.name
                    or not (member.isdir() or member.isfile() or member.issym())):
                raise ValueError("unsafe path or non-regular entry in tool4D TAR.XZ")
            destination = tools.joinpath(*path.parts)
            if destination in destinations:
                raise ValueError("duplicate tool4D archive path")
            destinations.add(destination)
            if (not destination.resolve().is_relative_to(base) or destination.is_symlink()
                    or any(parent.is_symlink() for parent in destination.parents)):
                raise ValueError("unsafe tool4D extraction destination")
            if member.issym():
                target = PurePosixPath(member.linkname)
                if (target.is_absolute() or "\\" in member.linkname or ":" in member.linkname
                        or not (destination.parent / member.linkname).resolve().is_relative_to(base)):
                    raise ValueError("unsafe tool4D symlink target")
                links[destination] = member.linkname
        if any(parent in links for destination in destinations for parent in destination.parents):
            raise ValueError("archive entries must not traverse a symlink")
        for member in members:
            destination = tools.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                destination.parent.mkdir(parents=True, exist_ok=True)
                with packed.extractfile(member) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                destination.chmod(member.mode & 0o777 or 0o644)
        created = []
        try:
            for destination, target in links.items():
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.symlink_to(target)
                created.append(destination)
            for destination in created:
                if not destination.resolve().is_relative_to(base):
                    raise ValueError("tool4D symlink chain escapes extraction directory")
        except (ValueError, OSError, RuntimeError):
            for destination in created:
                destination.unlink()
            raise


TOOL4D_HOSTS = {
    # host: (package.json key, platform, arch, URL os segment, archive name, executable path)
    "macos-arm64": ("tool", "macos", "arm", "mac", "tool4d_arm64.tar.xz",
                    ("tool4d.app", "Contents", "MacOS", "tool4d")),
    "windows-x64": ("tool_windows", "win", "x64", "win", "tool4d_win.tar.xz",
                    ("tool4d", "tool4d.exe")),
}


def require_tool4d_host():
    """Return the native tool4d host; emulated/translated hosts are rejected."""
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if system == "Windows":
        from build_cli import native_target
        try:
            if native_target() == "windows-x64":
                return "windows-x64"
        except ValueError:
            pass
    raise ValueError("pinned tool4d requires native macOS ARM64 or native Windows x64")


def tool4d_executable(root=ROOT, host=None):
    host = host or require_tool4d_host()
    return Path(root) / ".tools" / Path(*TOOL4D_HOSTS[host][5])


def tool_pin(root=ROOT, host="macos-arm64"):
    """Derive the official URL from versioned public metadata, not mutable latest."""
    if host not in TOOL4D_HOSTS:
        raise ValueError("unsupported tool4d host: " + str(host))
    key, platform_name, arch, segment, filename, _ = TOOL4D_HOSTS[host]
    manifest = json.loads((Path(root) / "package.json").read_text(encoding="utf-8"))
    tool = manifest.get(key)
    if not isinstance(tool, dict):
        raise ValueError(f"package.json.{key} must specify the approved compiler build and SHA256")
    if (tool.get("platform") != platform_name or tool.get("arch") != arch
            or not isinstance(tool.get("branch"), str) or not re.fullmatch(r"[0-9]+\.x", tool["branch"])
            or not isinstance(tool.get("version"), str) or not re.fullmatch(r"[0-9]+\.[0-9]+", tool["version"])
            or not isinstance(tool.get("build"), str) or not re.fullmatch(r"[1-9][0-9]*", tool["build"])
            or not isinstance(tool.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", tool["sha256"])):
        raise ValueError(f"package.json.{key} requires fixed numeric build, {platform_name}/{arch} and a 64-hex SHA256")
    url = (f"https://resources-download.4d.com/release/{tool['branch']}/"
           f"{tool['version']}/{tool['build']}/{segment}/{filename}")
    return url, tool["sha256"].lower()


def resolve_tool_pin(root=ROOT, *, url=None, digest=None, host="macos-arm64"):
    if url is not None or digest is not None:
        if not url or not digest:
            raise ValueError("--url and --sha256 must be supplied together and nonempty")
        return checked_tool_pin(url, digest)
    env_url = os.environ.get("TOOL4D_URL", "")
    env_digest = os.environ.get("TOOL4D_SHA256", "")
    if env_url or env_digest:
        if not env_url or not env_digest:
            raise ValueError("TOOL4D_URL and TOOL4D_SHA256 overrides must be supplied together")
        return checked_tool_pin(env_url, env_digest)
    return checked_tool_pin(*tool_pin(root, host))


def checked_tool_pin(url, digest):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname != "resources-download.4d.com"
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
        raise ValueError("official HTTPS tool4d URL and 64-hex SHA256 are required")
    if any(part.lower() == "latest" for part in
           PurePosixPath(urllib.parse.unquote(parsed.path)).parts):
        raise ValueError("tool4d URL must pin a concrete build, not latest")
    return url, digest.lower()


def checked_download_url(url):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in TOOL4D_DOWNLOAD_HOSTS
            or parsed.username or parsed.password or parsed.fragment or parsed.port not in (None, 443)):
        raise ValueError("tool4D download redirected outside official HTTPS origin")
    return url


class Tool4DRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        checked_download_url(newurl)
        return super().redirect_request(request, response, code, message, headers, newurl)


def open_tool4d_url(url):
    checked_download_url(url)
    return urllib.request.build_opener(Tool4DRedirectHandler()).open(url, timeout=120)


def download_tool4d(root=ROOT, *, url=None, digest=None, host="macos-arm64"):
    """Download a concrete, SHA-256-pinned HTTPS TAR.XZ/TAR.BZ2 or ZIP archive."""
    root = Path(root).resolve()
    url, digest = resolve_tool_pin(root, url=url, digest=digest, host=host)
    top, *inner = TOOL4D_HOSTS[host][5]
    tools = root / ".tools"
    if any(path.is_symlink() for path in [tools, *tools.parents]):
        raise ValueError(".tools must not be a symlink")
    tools.mkdir(exist_ok=True)
    archive = tools / "tool4d.download"
    if archive.is_symlink():
        raise ValueError("tool4D download destination must not be a symlink")
    sha = hashlib.sha256()
    try:
        with open_tool4d_url(url) as response, archive.open("wb") as output:
            checked_download_url(response.geturl())
            while chunk := response.read(1024 * 1024):
                sha.update(chunk)
                output.write(chunk)
    except (OSError, ValueError):
        archive.unlink(missing_ok=True)
        raise
    if sha.hexdigest().lower() != digest.lower():
        archive.unlink()
        raise ValueError("tool4D SHA-256 mismatch")
    try:
        with tempfile.TemporaryDirectory(prefix="tool4d-stage-", dir=tools) as temporary:
            stage = Path(temporary)
            if not zipfile.is_zipfile(archive):
                extract_tar(archive, stage)
            else:
                extract_zip(archive, stage)
            app = stage / top
            executable = app.joinpath(*inner)
            if not executable.is_file() or executable.is_symlink():
                raise ValueError("archive must contain " + "/".join((top, *inner)))
            executable.chmod(0o755)
            installed = tools / top
            if installed.is_symlink():
                raise ValueError(f"installed {top} must not be a symlink")
            if installed.exists():
                raise ValueError(f"{top} already exists; inspect/remove only that tool before reinstalling")
            app.rename(installed)
        (tools / "tool4d-install.json").write_text(json.dumps({
            "url": url, "sha256": sha.hexdigest(), "host": host,
        }, indent=2) + "\n", encoding="utf-8")
    finally:
        archive.unlink(missing_ok=True)
    return installed.joinpath(*inner)


def extract_zip(archive, tools):
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        names = set()
        for member in members:
            path = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (not member.filename or "\\" in member.filename or path.is_absolute()
                    or ".." in path.parts or ":" in member.filename
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)
                    or path.as_posix() in names):
                raise ValueError("unsafe path or non-regular file in tool4D archive")
            names.add(path.as_posix())
            destination = tools.joinpath(*path.parts)
            if not destination.resolve().is_relative_to(tools.resolve()):
                raise ValueError("tool4D archive would escape .tools")
            if destination.is_symlink() or any(parent.is_symlink() for parent in destination.parents):
                raise ValueError("symlink in tool4D extraction destination")
        for member in members:
            path = tools.joinpath(*PurePosixPath(member.filename).parts)
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipped.open(member) as source, path.open("wb") as output:
                    shutil.copyfileobj(source, output)
                path.chmod((member.external_attr >> 16) & 0o777 or 0o644)
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("matrix", "validate", "assemble", "download-tool4d"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--local-development", action="store_true",
                        help="assemble only the native macOS development profile; never a production resource")
    parser.add_argument("--tag", help="prefix-free SemVer release tag; defaults to GITHUB_REF_NAME")
    parser.add_argument("--url", help="optional official URL override, paired with --sha256")
    parser.add_argument("--sha256", help="optional approved hash override; otherwise env pair/package.json.tool")
    args = parser.parse_args()
    try:
        if args.command == "download-tool4d":
            host = require_tool4d_host()
            print(download_tool4d(args.root, url=args.url, digest=args.sha256, host=host))
            return
        if args.release and not os.environ.get("GITHUB_REPOSITORY"):
            raise ValueError("GITHUB_REPOSITORY is required for release validation")
        config = load_config(
            args.root, initialized=args.release or args.command == "assemble",
            repository=os.environ.get("GITHUB_REPOSITORY"),
            tag=(args.tag if args.tag is not None else os.environ.get("GITHUB_REF_NAME", "")) if args.release else None)
        if args.release and os.environ.get("FOURD_ENABLED") != "true":
            raise ValueError("releases require FOURD_ENABLED=true")
        if args.release and config.get("resource_targets") == ["windows-x64"]:
            # Windows-only releases are compiled and host-accepted by native Windows x64 tool4d.
            tool_pin(args.root, "windows-x64")
        if args.local_development and args.command != "assemble":
            raise ValueError("--local-development applies only to assemble")
        if args.command == "matrix":
            value = json.dumps(matrix(config), separators=(",", ":"))
            print(value)
            if output := os.environ.get("GITHUB_OUTPUT"):
                with open(output, "a", encoding="utf-8") as stream:
                    stream.write(f"matrix={value}\n")
                    stream.write(f"initialized={str(config['initialized']).lower()}\n")
                    stream.write(f"language={config['language'] or 'none'}\n")
        elif args.command == "assemble":
            destination = assemble(args.root, args.local_development)
            print(destination)
            if output := os.environ.get("GITHUB_OUTPUT"):
                with open(output, "a", encoding="utf-8") as stream:
                    stream.write(f"resources={destination.resolve()}\n")
        else:
            print("configuration validated")
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, tarfile.TarError,
            zipfile.BadZipFile, subprocess.CalledProcessError) as error:
        parser.exit(2, f"delivery configuration failed: {error}\n")


if __name__ == "__main__":
    main()
