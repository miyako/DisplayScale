"""Static delivery tests: synthetic binary headers never execute or use toolchains."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from contextlib import redirect_stderr, redirect_stdout
import build_cli
import accept_local
import ci_config
import package_component
from compile_component import input_digest, output_digest
from build_provenance import record


def synthetic_universal():
    result = bytearray(112)
    struct.pack_into(">II", result, 0, 0xCAFEBABE, 2)
    for index, cpu in enumerate((0x01000007, 0x0100000C)):
        offset = 48 + index * 32
        struct.pack_into(">IIIII", result, 8 + index * 20, cpu, 0, offset, 32, 0)
        struct.pack_into("<II", result, offset, 0xFEEDFACF, cpu)
    return bytes(result)


def synthetic_pe():
    result = bytearray(128)
    result[:2] = b"MZ"
    struct.pack_into("<I", result, 0x3C, 64)
    result[64:68] = b"PE\0\0"
    struct.pack_into("<H", result, 68, 0x8664)
    struct.pack_into("<H", result, 88, 0x20B)
    return bytes(result)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix=".delivery-test-", dir=ROOT)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.config = {
            "schema": 1, "initialized": True, "repository": "example-component",
            "namespace": "Example", "cli": "example-cli", "language": "go",
            "feature": "greeting", "version": "0.1.0",
        }
        repository_environment = patch.dict(
            os.environ, {"GITHUB_REPOSITORY": "owner/example-component"})
        repository_environment.start()
        self.addCleanup(repository_environment.stop)
        self.write_config()
        self.component = self.root / "component" / self.config["repository"]
        self.project = self.component / "Project" / "example-component.4DProject"
        self.project.parent.mkdir(parents=True)
        self.project.write_text("{}", encoding="utf-8")
        sources = self.project.parent / "Sources"
        sources.mkdir()
        (sources / "source.4dm").write_text("// excluded interpreted source\n", encoding="utf-8")
        for directory in ("Classes", "Methods"):
            (sources / directory).mkdir()
            (sources / directory / "excluded.4dm").write_text("// excluded\n", encoding="utf-8")
            (sources / directory / "metadata.json").write_text("{}", encoding="utf-8")
        (sources / "Classes/Greeting.4dm").write_text("// synthetic feature class\n")
        (self.root / "cli").mkdir()
        (self.root / "cli/main.go").write_text("// synthetic CLI source\n")
        for name in ("settings.4DSettings", "catalog.4DCatalog", "dependencies.json", "folders.json"):
            (sources / name).write_text("{}", encoding="utf-8")
        (sources / "settings.4DSettings").write_text('<preferences><com.4d><general component_classStore_name="Example"/></com.4d></preferences>')
        (sources / "catalog.4DCatalog").write_text('<base name="example-component"/>')
        compiled = self.project.parent / "DerivedData" / "CompiledCode"
        compiled.mkdir(parents=True)
        for name in ("classes.json", "map.json"):
            (compiled / name).write_text("{}", encoding="utf-8")
        for architecture in ("MX64", "IX64"):
            (compiled / (architecture + " 123")).write_bytes(b"synthetic compiled code")
        for name in ("methodAttributes.json", "formAttributes.json", "webservices.json", "excluded-cache.json"):
            (compiled.parent / name).write_text("{}", encoding="utf-8")
        libraries = self.component / "Libraries"
        libraries.mkdir()
        (libraries / "lib4d-arm64.dylib").write_bytes(b"static test compiled placeholder")
        (libraries / "lib4d-arm64.dylib").chmod(0o755)
        documentation = self.component / "Documentation" / "Classes"
        documentation.mkdir(parents=True)
        (documentation / "Example.md").write_text("Documentation\n", encoding="utf-8")
        self.mac = self.component / "Resources" / "bin" / "macOS" / "example-cli"
        self.windows = self.component / "Resources" / "bin" / "Windows" / "example-cli.exe"
        for path, content in ((self.mac, synthetic_universal()), (self.windows, synthetic_pe())):
            path.parent.mkdir(parents=True)
            path.write_bytes(content)
        resources = self.component / "Resources"
        (resources / "licenses").mkdir()
        for language, name in package_component.RUNTIME_NOTICES.items():
            source = ROOT / ("cli" if json.loads((ROOT / "template.json").read_text())["initialized"] else "cli-starters/" + language) / "licenses" / name
            # Synthetic delivery tests may select an unrelated language after initialization.
            (resources / "licenses" / name).write_bytes(source.read_bytes() if source.is_file() else b"synthetic runtime notice")
        (resources / "logo.png").write_bytes(b"synthetic PNG fixture")
        (resources / "logo.svg").write_text("<svg/>", encoding="utf-8")
        (resources / "en.lproj").mkdir()
        (resources / "en.lproj" / "syntaxEN.json").write_text("{}", encoding="utf-8")
        (self.root / "LICENSE").write_text("test license\n", encoding="utf-8")
        self.marker = self.root / "build" / "compile-status.json"
        self.marker.parent.mkdir()
        self.status = {
            "success": True, "targets": ["x86_64_generic", "arm64_macOS_lib"],
            "project": self.project.relative_to(self.root).as_posix(),
        }
        self.write_status()

    def write_config(self):
        (self.root / "template.json").write_text(json.dumps(self.config), encoding="utf-8")
        (self.root / "package.json").write_text(
            json.dumps({"name": self.config["repository"], "version": self.config["version"]}), encoding="utf-8")

    def write_status(self):
        self.status["input_sha256"] = input_digest(self.root)
        self.status["output_sha256"] = output_digest(self.component)
        self.marker.write_text(json.dumps(self.status), encoding="utf-8")

    def package(self, **options):
        return package_component.package(
            self.root, repository="owner/example-component", tag="0.1.0", **options)

    def test_uninitialized_fails_and_has_no_native_jobs(self):
        self.config.update(initialized=False, repository="4d-component-template", language=None)
        self.write_config()
        self.assertEqual(ci_config.matrix(ci_config.load_config(self.root)), {"include": []})
        with self.assertRaisesRegex(ValueError, "initialize"):
            package_component.package(self.root, repository="owner/4d-component-template", tag="0.1.0")

    def test_matrix_only_selected_language(self):
        for language in ("go", "rust", "cpp"):
            self.config["language"] = language
            self.write_config()
            entries = ci_config.matrix(ci_config.load_config(self.root))["include"]
            self.assertEqual([entry["target"] for entry in entries], list(ci_config.TARGETS))
            self.assertEqual([entry["runner"] for entry in entries],
                             ["macos-15-intel", "macos-15", "windows-2022"])
            self.assertEqual({entry["language"] for entry in entries}, {language})

    def windows_scope(self):
        self.config.update(resource_targets=["windows-x64"], unsupported_backend_platforms=["Darwin"])
        self.write_config()

    def build_fixture(self, target, data, tested=True):
        path = self.root / "build" / target / (self.config["cli"] + (".exe" if target == "windows-x64" else ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        record(self.root, target, path, tested, "synthetic fixture, not execution evidence")
        return path

    def thin_fixture(self):
        data = bytearray(32)
        struct.pack_into("<IIII", data, 0, 0xFEEDFACF, 0x0100000C, 0, 2)
        return bytes(data)

    def test_windows_production_assembly_and_package_have_no_mac_backend(self):
        self.windows_scope()
        self.build_fixture("windows-x64", synthetic_pe())
        ci_config.assemble(self.root)
        self.assertFalse(self.mac.exists())
        self.write_status()
        archive = self.package()
        with zipfile.ZipFile(archive) as packed:
            self.assertFalse(any("/bin/macOS/" in name or "DEVELOPMENT" in name for name in packed.namelist()))
            self.assertTrue(any("/bin/Windows/" in name for name in packed.namelist()))

    def test_assembly_still_rejects_a_conflicting_repository_environment(self):
        self.windows_scope()
        self.build_fixture("windows-x64", synthetic_pe())
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/AnotherComponent"}):
            with self.assertRaisesRegex(ValueError, "actual repository does not match"):
                ci_config.assemble(self.root)

    def test_development_is_explicit_native_thin_and_cannot_be_production(self):
        self.windows_scope()
        self.build_fixture("macos-arm64", self.thin_fixture())
        with patch.object(build_cli, "native_target", return_value="macos-arm64"):
            ci_config.assemble(self.root, local_development=True)
            self.assertFalse(self.windows.exists())
            self.write_status()
            archive = self.package(local_development=True)
            self.assertEqual(archive.parent.name, "development")
            with zipfile.ZipFile(archive) as packed:
                marker = json.loads(packed.read("example-component.4dbase/DEVELOPMENT.json"))
                self.assertIs(marker["feature_support"], False)
                self.assertIs(marker["release_ready"], False)
                self.assertFalse(any("/bin/Windows/" in name for name in packed.namelist()))
            with self.assertRaises(ValueError):
                self.package()

    def test_resource_profile_rejects_stale_source_tampering_extra_binary_and_unexecuted_build(self):
        self.windows_scope()
        self.build_fixture("windows-x64", synthetic_pe(), tested=False)
        with self.assertRaisesRegex(ValueError, "native CLI execution"):
            ci_config.assemble(self.root)
        self.build_fixture("windows-x64", synthetic_pe())
        ci_config.assemble(self.root)
        self.write_status()
        self.windows.write_bytes(synthetic_pe() + b"tampered")
        self.write_status()
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.package()
        ci_config.assemble(self.root)
        self.mac.parent.mkdir(parents=True)
        self.mac.write_bytes(self.thin_fixture())
        self.write_status()
        with self.assertRaisesRegex(ValueError, "unexpected"):
            self.package()
        ci_config.assemble(self.root)
        (self.root / "cli/main.go").write_text("changed source")
        self.write_status()
        with self.assertRaisesRegex(ValueError, "provenance"):
            self.package()

    def test_development_thin_header_and_target_scope_fail_closed(self):
        self.windows_scope()
        self.mac.write_bytes(self.thin_fixture())
        package_component.validate_resources(self.component, self.config["cli"], ("macos-arm64",))
        with self.assertRaisesRegex(ValueError, "matching native thin"):
            package_component.validate_resources(self.component, self.config["cli"], ("macos-x64",))
        self.config["resource_targets"] = ["macos-arm64"]
        self.write_config()
        with self.assertRaisesRegex(ValueError, "Windows x64 only"):
            ci_config.load_config(self.root)

    def test_windows_release_requires_hosted_opt_in_and_native_windows_tool4d_pin(self):
        self.windows_scope()
        pin = {"platform": "win", "branch": "20.x", "version": "20.7", "build": "101905", "arch": "x64",
               "sha256": "31d5300ca38df9b18b32c07835ab9b1e1cf0deee6c936a382581723ed0edd4dc"}

        def validate(enabled, tool_windows):
            metadata = {"name": self.config["repository"], "version": self.config["version"]}
            if tool_windows is not None:
                metadata["tool_windows"] = tool_windows
            (self.root / "package.json").write_text(json.dumps(metadata), encoding="utf-8")
            environment = {"GITHUB_REPOSITORY": "owner/example-component"}
            if enabled:
                environment["FOURD_ENABLED"] = "true"
            with patch.dict(os.environ, environment, clear=True), patch.object(
                    sys, "argv", ["ci_config.py", "validate", "--release", "--tag", "0.1.0",
                                  "--root", str(self.root)]), redirect_stdout(io.StringIO()):
                ci_config.main()

        for enabled, tool_windows in ((True, None), (False, pin), (True, {**pin, "platform": "mac"}),
                                      (True, {**pin, "arch": "arm"}), (True, {**pin, "sha256": "0" * 63})):
            with self.subTest(enabled=enabled, tool_windows=tool_windows), self.assertRaises(SystemExit) as caught, \
                    redirect_stderr(io.StringIO()):
                validate(enabled, tool_windows)
            self.assertEqual(caught.exception.code, 2)
        validate(True, pin)
        self.assertEqual(ci_config.tool_pin(self.root, "windows-x64")[0],
                         "https://resources-download.4d.com/release/20.x/20.7/101905/win/tool4d_win.tar.xz")

    def test_platform_cli_vectors_do_not_claim_darwin_feature_success(self):
        contract = self.root / "contract.json"
        version = {"args": ["--version"], "exitCode": 0, "stdout": "version\n", "stderr": ""}
        windows = {"platforms": ["Windows"], "args": ["monitors"], "exitCode": 0,
                   "stdout": "monitors\n", "stderr": ""}
        unsupported = {"platforms": ["Darwin"], "args": ["monitors"], "exitCode": 3,
                       "stdout": "", "stderr": "UNSUPPORTED_PLATFORM\n"}
        contract.write_text(json.dumps({"schema": 1, "cases": [version, windows, unsupported]}))
        results = [subprocess.CompletedProcess([], 0, b"version\n", b""),
                   subprocess.CompletedProcess([], 3, b"", b"UNSUPPORTED_PLATFORM\n")]
        with patch.object(build_cli.platform, "system", return_value="Darwin"):
            with self.assertRaisesRegex(ValueError, "feature success"):
                build_cli.smoke_test("fixture", "0.1.0", contract)
            with patch.object(build_cli.subprocess, "run", side_effect=results) as run:
                build_cli.smoke_test("fixture", "0.1.0", contract, unsupported_backend=True)
                self.assertEqual(run.call_count, 2)
            contract.write_text(json.dumps({"schema": 1, "cases": [version]}))
            with self.assertRaisesRegex(ValueError, "UNSUPPORTED_PLATFORM"):
                build_cli.smoke_test("fixture", "0.1.0", contract, unsupported_backend=True)

    def test_development_acceptance_forwards_profile_and_never_claims_windows_execution(self):
        self.windows_scope()
        tool = self.root / "test-only-tool4d"
        tool.write_bytes(b"mock compiler; never executed")
        archive = self.root / "dist/development/example-component.zip"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"mock artifact; not runtime evidence")
        source = {"success": True, "finished": True, "compiled": False}
        compiled = {**source, "compiled": True}
        with patch.object(build_cli, "native_target", return_value="macos-arm64"), patch.object(
                accept_local, "native_target", return_value="macos-arm64"), patch.object(
                accept_local, "require_tool4d_host"), patch.object(accept_local, "doctor", return_value={}), patch.object(
                accept_local, "build") as build, patch.object(accept_local, "assemble") as assemble, patch.object(
                accept_local, "validate_resources"), patch.object(accept_local, "test_4d", side_effect=[source, compiled]), patch.object(
                accept_local, "compile_component", return_value={"success": True}), patch.object(
                accept_local, "package", return_value=archive) as package, patch.object(
                accept_local, "unpack_for_test", return_value=self.root / "unpacked.4dbase"), patch.object(
                accept_local.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "test-only tool4d identity\n", "")):
            report = accept_local.accept(self.root, "owner/example-component", tool, local_development=True)
        assemble.assert_called_once_with(self.root, True)
        self.assertTrue(package.call_args.kwargs["local_development"])
        self.assertEqual(build.call_args.args[1], "macos-arm64")
        self.assertEqual(report["scope"], "local-development")
        self.assertFalse(report["feature_support"])
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["steps"]["cli_test_windows-x64"]["status"], "not_run")
        self.assertEqual(report["steps"]["windows_4d"]["status"], "not_run")
        self.assertTrue(archive.with_suffix(".acceptance.json").is_file())

    def test_assembly_places_file_before_variadic_verify_arch_option(self):
        inputs = []
        for target in ci_config.TARGETS:
            filename = self.config["cli"] + (".exe" if target == "windows-x64" else "")
            path = self.root / "build" / target / filename
            path.parent.mkdir()
            path.write_bytes(synthetic_pe() if target == "windows-x64" else b"mock native slice")
            record(self.root, target, path, True, "synthetic test")
            inputs.append(path)
        with patch.dict(os.environ, {}, clear=True), patch("build_provenance.commit", return_value=None), patch.object(ci_config.subprocess, "run") as run:
            destination = ci_config.assemble(self.root)
        self.assertEqual(run.call_args_list, [
            unittest.mock.call(["lipo", "-create", str(inputs[0]), str(inputs[1]),
                                "-output", str(self.mac)], check=True),
            unittest.mock.call(["lipo", str(self.mac), "-verify_arch", "x86_64", "arm64"], check=True),
        ])
        self.assertEqual(destination, self.mac.parent.parent)
        self.assertEqual(self.mac.stat().st_mode & 0o777, 0o755)
        self.assertEqual(self.windows.read_bytes(), inputs[2].read_bytes())

    def test_all_languages_preserve_repository_release_asset_identity(self):
        for language in ("go", "rust", "cpp"):
            self.config["language"] = language
            self.write_config()
            self.write_status()
            archive = self.package(language=language)
            self.assertEqual(archive.name, self.config["repository"] + ".zip")
            with zipfile.ZipFile(archive) as packed:
                prefix = self.config["repository"] + ".4dbase/"
                self.assertTrue(all(name.startswith(prefix) for name in packed.namelist()))
                project_name = prefix + self.config["repository"] + ".4DZ"
                with zipfile.ZipFile(io.BytesIO(packed.read(project_name))) as project:
                    self.assertIn("Project/" + self.config["repository"] + ".4DProject",
                                  project.namelist())

    def test_wrong_repository(self):
        with self.assertRaisesRegex(ValueError, "actual repository"):
            package_component.package(self.root, repository="owner/wrong", tag="0.1.0")

    def test_wrong_package_name(self):
        (self.root / "package.json").write_text('{"name":"wrong"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "package.json name"):
            self.package()

    def test_wrong_package_version(self):
        (self.root / "package.json").write_text('{"name":"example-component","version":"9.0.0"}')
        with self.assertRaisesRegex(ValueError, "package.json version"):
            self.package()

    def test_wrong_4d_project_namespace_and_catalog(self):
        settings = self.project.parent / "Sources/settings.4DSettings"
        original = settings.read_text()
        settings.write_text(original.replace('"Example"', '"Wrong"'))
        with self.assertRaisesRegex(ValueError, "namespace"):
            self.package()
        settings.write_text(original)
        catalog = self.project.parent / "Sources/catalog.4DCatalog"
        catalog.write_text('<base name="wrong"/>')
        with self.assertRaisesRegex(ValueError, "catalog name"):
            self.package()

    def test_wrong_language(self):
        with self.assertRaisesRegex(ValueError, "language"):
            self.package(language="rust")
        self.config["language"] = "python"
        self.write_config()
        with self.assertRaisesRegex(ValueError, "language"):
            self.package()

    def test_initialized_configuration_uses_initializer_reserved_name_rules(self):
        for field in ("repository", "cli"):
            original = self.config[field]
            for name in ("con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9"):
                self.config[field] = name
                self.write_config()
                with self.subTest(field=field, name=name), self.assertRaisesRegex(ValueError, "reserved"):
                    ci_config.load_config(self.root)
            self.config[field] = original
            self.write_config()

    def test_bad_tag_or_semver(self):
        for tag in ("v0.1.0", "0.2.0", "0.1.0/../../escape", "20R3.2"):
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, "tag"):
                package_component.package(self.root, repository="owner/example-component", tag=tag)
        for version in ("01.1.0", "0.1", "0.1.0-01", "0.1.0\n", "0.1.0/escape"):
            self.config["version"] = version
            self.write_config()
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "SemVer"):
                ci_config.load_config(self.root)

    def test_missing_resources(self):
        for resource in (self.mac, self.windows):
            content = resource.read_bytes()
            resource.unlink()
            with self.assertRaisesRegex(ValueError, "missing regular native resource"):
                self.package()
            resource.write_bytes(content)

    def test_selected_runtime_notice_missing_or_empty_fails(self):
        notice = self.component / "Resources/licenses/Go-LICENSE.txt"
        original = notice.read_bytes()
        for empty in (False, True):
            if empty:
                notice.write_bytes(b"")
            else:
                notice.unlink()
            with self.assertRaisesRegex(ValueError, "redistribution notice"):
                self.package()
            notice.write_bytes(original)

    def test_fake_headers_rejected(self):
        self.mac.write_bytes(b"\xca\xfe\xba\xbe" + b"\0" * 64)
        with self.assertRaisesRegex(ValueError, "exactly Intel and ARM"):
            self.package()
        self.mac.write_bytes(synthetic_universal())
        self.windows.write_bytes(b"MZ" + b"\0" * 128)
        with self.assertRaisesRegex(ValueError, "PE32"):
            self.package()

    def test_architecture_and_slice_bounds(self):
        data = bytearray(synthetic_universal())
        struct.pack_into(">I", data, 20, 1000)
        self.mac.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "bounds"):
            self.package()
        self.mac.write_bytes(synthetic_universal())
        data = bytearray(synthetic_pe())
        struct.pack_into("<H", data, 68, 0xAA64)
        self.windows.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "x64"):
            self.package()

    def test_missing_failed_or_wrong_compile_marker(self):
        self.marker.unlink()
        with self.assertRaisesRegex(ValueError, "compile-status"):
            self.package()
        for updates in (
            {"success": False}, {"success": "true"}, {"targets": ["x86_64_generic"]},
            {"project": "component/other/Project/other.4DProject"},
        ):
            original = self.status.copy()
            self.status.update(updates)
            self.write_status()
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.package()
            self.status = original

    def test_empty_libraries_rejected(self):
        (self.component / "Libraries" / "lib4d-arm64.dylib").unlink()
        with self.assertRaisesRegex(ValueError, "Libraries"):
            self.package()

    def test_stale_compile_provenance_rejected(self):
        paths = [
            self.root / "template.json", self.root / "package.json", self.root / "LICENSE",
            self.project, self.project.parent / "Sources" / "settings.4DSettings",
            self.component / "Documentation" / "Classes" / "Example.md",
            self.mac, self.windows, self.component / "Resources" / "logo.svg",
        ]
        for path in paths:
            original = path.read_bytes()
            updated = original + (b" " if path.suffix in {".json", ".4DProject", ".4DSettings"} else b"changed")
            path.write_bytes(updated)
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, "input_sha256"):
                self.package()
            path.write_bytes(original)
        self.status.pop("input_sha256")
        self.marker.write_text(json.dumps(self.status), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input_sha256"):
            self.package()

    def test_generated_syntax_does_not_invalidate_but_compiled_tampering_does(self):
        (self.component / "Resources/en.lproj/syntaxEN.json").write_text(
            '{"generated":true}', encoding="utf-8")
        self.package()
        (self.project.parent / "DerivedData/CompiledCode/map.json").write_text(
            '{"generated":true}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "output_sha256"):
            self.package()

    def test_required_compiled_code_rejected_if_missing_or_empty(self):
        compiled = self.project.parent / "DerivedData" / "CompiledCode"
        for path in (compiled / "classes.json", compiled / "map.json", compiled / "MX64 123"):
            content = path.read_bytes()
            for absent in (False, True):
                if absent:
                    path.unlink()
                else:
                    path.write_bytes(b"")
                with self.subTest(path=path.name, absent=absent), self.assertRaisesRegex(
                        ValueError, "compiled|MX64"):
                    self.package()
                path.write_bytes(content)

    def test_deterministic_zip_root_modes_and_exclusions(self):
        for directory in ("Data", "Logs", "DerivedData", ".git"):
            path = self.component / directory / "excluded"
            path.parent.mkdir()
            path.write_text("exclude", encoding="utf-8")
        first = self.package().read_bytes()
        self.mac.chmod(0o600)
        self.assertEqual(first, self.package().read_bytes())
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            names = archive.namelist()
            prefix = "example-component.4dbase/"
            self.assertTrue(all(name.startswith(prefix) for name in names))
            self.assertIn(prefix + "example-component.4DZ", names)
            self.assertFalse(any(name.startswith(prefix + "Project/") for name in names))
            with zipfile.ZipFile(io.BytesIO(archive.read(prefix + "example-component.4DZ"))) as packed:
                inner = packed.namelist()
                self.assertIn("Project/example-component.4DProject", inner)
                for directory in ("Project/", "Project/Sources/", "Project/DerivedData/",
                                  "Project/DerivedData/CompiledCode/"):
                    entry = packed.getinfo(directory)
                    self.assertTrue(entry.is_dir())
                    self.assertTrue(stat.S_ISDIR(entry.external_attr >> 16))
                    self.assertEqual((entry.external_attr >> 16) & 0o777, 0o755)
                for metadata in ("settings.4DSettings", "catalog.4DCatalog", "dependencies.json", "folders.json"):
                    self.assertIn("Project/Sources/" + metadata, inner)
                for name in ("classes.json", "map.json", "MX64 123", "IX64 123"):
                    self.assertIn("Project/DerivedData/CompiledCode/" + name, inner)
                for name in ("methodAttributes.json", "formAttributes.json", "webservices.json"):
                    self.assertIn("Project/DerivedData/" + name, inner)
                self.assertNotIn("Project/DerivedData/excluded-cache.json", inner)
                self.assertFalse(any(name.endswith(".4dm") or "/Classes/" in name
                                     or "/Methods/" in name or "/Libraries/" in name for name in inner))
                self.assertTrue(all(entry.date_time == (1980, 1, 1, 0, 0, 0)
                                    for entry in packed.infolist()))
            self.assertIn(prefix + "Libraries/lib4d-arm64.dylib", names)
            self.assertIn(prefix + "Documentation/Classes/Example.md", names)
            for name in ("logo.png", "logo.svg", "en.lproj/syntaxEN.json"):
                self.assertIn(prefix + "Resources/" + name, names)
            self.assertEqual(archive.read(prefix + "Resources/licenses/LICENSE"), b"test license\n")
            self.assertNotIn(prefix + "LICENSE", names)
            self.assertFalse(any("excluded" in name for name in names))
            for entry in archive.infolist():
                self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                mode = entry.external_attr >> 16
                self.assertTrue(stat.S_ISDIR(mode) if entry.is_dir() else stat.S_ISREG(mode))
                executable = "/bin/" in entry.filename or entry.filename.endswith("lib4d-arm64.dylib")
                self.assertEqual(mode & 0o777, 0o755 if entry.is_dir() or executable else 0o644)

    def test_unpack_actual_archive_preserves_resources_and_compiled_project(self):
        archive = self.package()
        component = package_component.unpack_for_test(self.root, archive)
        self.assertEqual(component, self.root / "build" / "release-test" / "example-component.4dbase")
        self.assertEqual((component / "Resources/bin/macOS/example-cli").read_bytes(), synthetic_universal())
        self.assertEqual((component / "Resources/bin/macOS/example-cli").stat().st_mode & 0o777, 0o755)
        self.assertTrue((component / "example-component.4DZ").is_file())
        self.assertEqual((component / "Libraries/lib4d-arm64.dylib").stat().st_mode & 0o777, 0o755)
        self.assertFalse((component / "Project").exists())
        stale = component / "stale"
        stale.write_text("previous run", encoding="utf-8")
        package_component.unpack_for_test(self.root, archive)
        self.assertFalse(stale.exists())

    def test_unpack_rejects_unsafe_archive_and_missing_packed_project(self):
        cases = [
            "../escape", "/escape", "other.4dbase/file",
            "example-component.4dbase/../escape", "example-component.4dbase/readme",
        ]
        for name in cases:
            with self.subTest(name=name), self.assertRaises(ValueError):
                package_component.unpack_for_test(self.root, io.BytesIO(self.archive_bytes(name)))
        with self.assertRaisesRegex(ValueError, "unsafe"):
            package_component.unpack_for_test(self.root, io.BytesIO(
                self.archive_bytes("example-component.4dbase/link", mode=stat.S_IFLNK | 0o777)))

    @unittest.skipUnless(os.name == "posix", "symlink creation requires POSIX")
    def test_symlinks_rejected(self):
        (self.component / "escape").symlink_to(self.root / "LICENSE")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            self.package()

    def test_native_mismatch_and_wrong_build_language(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(build_cli, "native_target", return_value="macos-arm64"):
            with self.assertRaisesRegex(ValueError, "native host"):
                build_cli.build(self.root, "macos-x64")
            with self.assertRaisesRegex(ValueError, "language"):
                build_cli.build(self.root, "macos-arm64", "rust")

    def test_toolchain_minimums_allow_supported_ci_pins(self):
        versions = [
            ("go", "go version go1.23.0 darwin/arm64", True),
            ("go", "go version go1.25.1 darwin/arm64", True),
            ("go", "go version go1.26.10 darwin/arm64", True),
            ("go", "go version go1.22.12 darwin/arm64", False),
            ("rust", "rustc 1.82.0 (test)", True),
            ("rust", "rustc 1.91.0 (test)", True),
            ("rust", "rustc 1.99.1 (test)", True),
            ("rust", "rustc 1.81.0 (test)", False),
        ]
        for language, version, valid in versions:
            with self.subTest(language=language, version=version), patch.object(
                    build_cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, version)):
                if valid:
                    build_cli.require_toolchain(language)
                else:
                    with self.assertRaisesRegex(ValueError, "or newer"):
                        build_cli.require_toolchain(language)

    def test_release_requires_opt_in(self):
        environment = {
            "GITHUB_REPOSITORY": "owner/example-component", "GITHUB_REF_NAME": "0.1.0",
            "FOURD_ENABLED": "false",
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
                sys, "argv", ["ci_config.py", "validate", "--release", "--root", str(self.root)]):
            with self.assertRaises(SystemExit) as caught:
                ci_config.main()
            self.assertEqual(caught.exception.code, 2)

    def test_manual_release_validates_explicit_tag_not_selected_branch_name(self):
        environment = {"GITHUB_REPOSITORY": "owner/example-component",
                       "GITHUB_REF_NAME": "main", "FOURD_ENABLED": "true"}
        package = json.loads((self.root / "package.json").read_text(encoding="utf-8"))
        package["tool"] = {"platform": "macos", "branch": "20.x", "version": "20.7", "build": "101905",
                           "arch": "arm", "sha256": "4" * 64}
        package["tool_windows"] = {"platform": "win", "branch": "20.x", "version": "20.7", "build": "101905",
                                   "arch": "x64", "sha256": "3" * 64}
        (self.root / "package.json").write_text(json.dumps(package), encoding="utf-8")
        with patch.dict(os.environ, environment, clear=True), patch.object(
                sys, "argv", ["ci_config.py", "validate", "--release", "--tag", "0.1.0",
                              "--root", str(self.root)]):
            ci_config.main()

    def archive_bytes(self, name, data=b"tool4d", mode=stat.S_IFREG | 0o755):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            archive.writestr(info, data)
        return output.getvalue()

    def download(self, data, digest=None, final_url=None):
        response = io.BytesIO(data)
        response.geturl = lambda: final_url or "https://resources-download.4d.com/fixed/tool4d.zip"
        environment = {
            "TOOL4D_URL": "https://resources-download.4d.com/fixed/tool4d.zip",
            "TOOL4D_SHA256": digest or hashlib.sha256(data).hexdigest(),
        }
        with patch.dict(os.environ, environment, clear=True), patch.object(
                ci_config, "open_tool4d_url", return_value=response):
            return ci_config.download_tool4d(self.root)

    def test_official_https_archive_cdn_redirect_preserves_pinned_sha256(self):
        data = self.archive_bytes("tool4d.app/Contents/MacOS/tool4d")
        cdn = "https://builds2.4d.com/4D_archive_tool-arm_mac_intl_release_20.x_101905.tar.xz?signature=test-only"
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.download(data, "0" * 64, final_url=cdn)
        executable = self.download(data, final_url=cdn)
        self.assertEqual(executable.read_bytes(), b"tool4d")
        self.assertEqual(executable.stat().st_mode & 0o777, 0o755)

    def test_tool4d_redirect_rejects_unrelated_insecure_or_credentialed_origins(self):
        data = self.archive_bytes("tool4d.app/Contents/MacOS/tool4d")
        for url in ("https://unrelated.example/tool4d.zip",
                    "https://builds2.4d.com.example/tool4d.zip",
                    "http://builds2.4d.com/tool4d.zip",
                    "http://resources-download.4d.com/tool4d.zip",
                    "https://user:password@builds2.4d.com/tool4d.zip",
                    "https://builds2.4d.com:444/tool4d.zip",
                    "https://builds2.4d.com/tool4d.zip#fragment"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "official HTTPS origin"):
                self.download(data, final_url=url)
            self.assertFalse((self.root / ".tools/tool4d.download").exists())
            self.assertFalse((self.root / ".tools/tool4d.app").exists())

    def test_cdn_is_redirect_only_not_an_approved_mutable_input_pin(self):
        for url in ("https://builds2.4d.com/fixed/tool4d.tar.xz",
                    "https://resources-download.4d.com/fixed/tool4d.tar.xz?signature=test-only"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "official HTTPS tool4d URL"):
                ci_config.checked_tool_pin(url, "0" * 64)

    def test_verified_tool4d_download_and_permissions(self):
        executable = self.download(self.archive_bytes("tool4d.app/Contents/MacOS/tool4d"))
        self.assertEqual(executable.read_bytes(), b"tool4d")
        self.assertEqual(executable.stat().st_mode & 0o777, 0o755)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.download(self.archive_bytes("tool4d.app/Contents/MacOS/tool4d"))
        self.assertEqual(executable.read_bytes(), b"tool4d")

    def test_official_vendor_cdn_redirect_keeps_pinned_hash_requirement(self):
        data = self.archive_bytes("tool4d.app/Contents/MacOS/tool4d")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.download(data, "0" * 64, "https://builds2.4d.com/fixed.tar.xz?Expires=123")
        executable = self.download(data, final_url="https://builds2.4d.com/fixed.tar.xz?Expires=123")
        self.assertEqual(executable.read_bytes(), b"tool4d")

    def test_unapproved_or_non_https_vendor_redirect_fails_closed(self):
        data = self.archive_bytes("tool4d.app/Contents/MacOS/tool4d")
        for url in ("http://builds2.4d.com/tool", "https://untrusted.invalid/tool",
                    "https://builds2.4d.com.untrusted.invalid/tool",
                    "https://user@builds2.4d.com/tool", "https://builds2.4d.com:8443/tool"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "official HTTPS"):
                self.download(data, final_url=url)

    def test_redirect_handler_rejects_every_unapproved_hop_before_following(self):
        handler = ci_config.Tool4DRedirectHandler()
        request = ci_config.urllib.request.Request("https://resources-download.4d.com/fixed/tool4d")
        for url in ("http://builds2.4d.com/tool", "https://untrusted.invalid/tool",
                    "https://user@builds2.4d.com/tool", "https://builds2.4d.com:8443/tool"):
            with self.subTest(url=url), patch.object(
                    ci_config.urllib.request.HTTPRedirectHandler, "redirect_request") as follow:
                with self.assertRaisesRegex(ValueError, "official HTTPS"):
                    handler.redirect_request(request, None, 302, "Found", {}, url)
                follow.assert_not_called()
        redirect = handler.redirect_request(request, None, 302, "Found", {},
                                            "https://builds2.4d.com/fixed.tar.xz?Expires=123")
        self.assertEqual(redirect.full_url, "https://builds2.4d.com/fixed.tar.xz?Expires=123")

    def test_tool4d_digest_and_unsafe_zip_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.download(self.archive_bytes("tool4d.app/Contents/MacOS/tool4d"), "0" * 64)
        for name in ("../escape", "/escape", "C:/escape", r"..\escape"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsafe"):
                self.download(self.archive_bytes(name))
        with self.assertRaisesRegex(ValueError, "non-regular"):
            self.download(self.archive_bytes("link", mode=stat.S_IFLNK | 0o777))

    def tar_bytes(self, entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:xz") as archive:
            for name, content, link in entries:
                entry = tarfile.TarInfo(name)
                if link is not None:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = link
                else:
                    entry.size = len(content)
                    entry.mode = 0o755
                archive.addfile(entry, io.BytesIO(content) if link is None else None)
        return output.getvalue()

    @unittest.skipUnless(os.name == "posix", "app framework symlinks require POSIX")
    def test_tar_xz_tool4d_and_internal_framework_links(self):
        data = self.tar_bytes([
            ("tool4d.app/Contents/MacOS/tool4d", b"static binary", None),
            ("tool4d.app/Contents/Frameworks/F.framework/Versions/A/F", b"framework", None),
            ("tool4d.app/Contents/Frameworks/F.framework/Versions/Current", b"", "A"),
            ("tool4d.app/Contents/Frameworks/F.framework/F", b"", "Versions/Current/F"),
        ])
        executable = self.download(data)
        self.assertEqual(executable.read_bytes(), b"static binary")
        framework = executable.parents[1] / "Frameworks/F.framework/F"
        self.assertTrue(framework.is_symlink())
        self.assertEqual(framework.read_bytes(), b"framework")

    def test_tar_traversal_and_external_links_rejected(self):
        entries = [
            [("../escape", b"bad", None)],
            [("tool4d.app/link", b"", "../../escape")],
            [("tool4d.app/link", b"", "/escape")],
            [("tool4d.app/link", b"", "other"), ("tool4d.app/link/file", b"bad", None)],
        ]
        for case in entries:
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, "unsafe|symlink"):
                self.download(self.tar_bytes(case))

    def test_duplicate_archive_paths_rejected(self):
        data = self.tar_bytes([("tool4d.app/file", b"one", None),
                               ("tool4d.app/./file", b"two", None)])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.download(data)

    def test_download_requires_concrete_pinned_url(self):
        with patch.dict(os.environ, {"TOOL4D_URL": "https://resources-download.4d.com/latest/tool4d.tar.xz",
                                     "TOOL4D_SHA256": "0" * 64}, clear=True):
            with self.assertRaisesRegex(ValueError, "concrete build"):
                ci_config.download_tool4d(self.root)


if __name__ == "__main__":
    unittest.main()
