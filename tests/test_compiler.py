import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compile_component", ROOT / "scripts/compile_component.py")
compiler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compiler)


class CompilerTests(unittest.TestCase):
    def setUp(self):
        platform.system()  # warm the cache: Windows otherwise shells out under the mocked subprocess
        self.temp = tempfile.TemporaryDirectory(prefix=".compiler-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        config = json.loads((ROOT / "template.json").read_text())
        config["initialized"] = True
        (self.root / "template.json").write_text(json.dumps(config))
        for name in ("package.json", "LICENSE"):
            shutil.copy2(ROOT / name, self.root / name)
        self.name = config["repository"]
        self.feature_class = config.get("feature_class", "Greeting")
        shutil.copytree(ROOT / "component" / self.name, self.root / "component" / self.name,
                        ignore=shutil.ignore_patterns("DerivedData", "Libraries"))
        self.project = self.root / "component" / self.name / "Project" / (self.name + ".4DProject")
        self.status = self.root / "build/compile-status.json"

    def test_fixture_excludes_live_generated_compiler_state(self):
        self.assertFalse((self.project.parent / "DerivedData").exists())
        self.assertFalse((self.project.parent.parent / "Libraries").exists())

    def result(self, args, **kwargs):
        self.assertNotIn("shell", kwargs)
        self.assertIn("--startup-method=Compile", args)
        parameter = [a for a in args if a.startswith("--user-param=")]
        self.assertEqual(len(parameter), 1)
        request = json.loads(Path(parameter[0].split("=", 1)[1]).read_text(encoding="utf-8"))
        self.assertEqual(request["targets"], compiler.compile_targets())
        self.status.write_text(json.dumps({"success": True, "project": self.project.as_posix(),
                                         "targets": request["targets"]}))

    def test_windows_compiles_x86_64_only_and_macos_both_targets(self):
        self.assertEqual(compiler.compile_targets("Windows"), ["x86_64_generic"])
        self.assertEqual(compiler.compile_targets("Darwin"), ["x86_64_generic", "arm64_macOS_lib"])

    def test_real_result_required_and_stale_status_removed(self):
        self.status.parent.mkdir()
        self.status.write_text('{"success":true}')
        with patch.object(compiler.subprocess, "run"), self.assertRaisesRegex(ValueError, "did not write"):
            compiler.compile_component(self.root, "/missing/tool4d")
        self.assertFalse(self.status.exists())

    def test_failed_compilation_not_success_shaped(self):
        def failure(*args, **kwargs):
            self.status.write_text('{"success":false,"errors":[{"message":"bad class"}]}')
        with patch.object(compiler.subprocess, "run", side_effect=failure), self.assertRaisesRegex(ValueError, "bad class"):
            compiler.compile_component(self.root, "/fake/tool4d")

    def test_failed_process_propagates(self):
        with patch.object(compiler.subprocess, "run", side_effect=subprocess.CalledProcessError(1, ["tool4d"])):
            with self.assertRaises(subprocess.CalledProcessError):
                compiler.compile_component(self.root, "/fake/tool4d")

    def test_success_binds_input_digest_and_identity(self):
        with patch.object(compiler.subprocess, "run", side_effect=self.result):
            status = compiler.compile_component(self.root, "/fake/tool4d")
        self.assertEqual(status["input_sha256"], compiler.input_digest(self.root))
        path = self.project.parent / "Sources/Classes" / (self.feature_class + ".4dm")
        path.write_text(path.read_text() + "\n")
        self.assertNotEqual(status["input_sha256"], compiler.input_digest(self.root))

    def test_changed_sources_during_compile_rejected(self):
        def changed(*args, **kwargs):
            self.result(*args, **kwargs)
            path = self.project.parent / "Sources/Classes" / (self.feature_class + ".4dm")
            path.write_text(path.read_text() + "\n")
        with patch.object(compiler.subprocess, "run", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "changed during compilation"):
                compiler.compile_component(self.root, "/fake/tool4d")

    def test_wrong_target_and_project_rejected(self):
        def wrong(*args, **kwargs):
            self.status.write_text('{"success":true,"project":"wrong","targets":["x86_64_generic"]}')
        with patch.object(compiler.subprocess, "run", side_effect=wrong):
            with self.assertRaisesRegex(ValueError, "required project and targets"):
                compiler.compile_component(self.root, "/fake/tool4d")

        def other_targets(*args, **kwargs):
            self.status.write_text(json.dumps({"success": True, "project": self.project.as_posix(),
                                               "targets": ["arm64_macOS_lib"]}))
        with patch.object(compiler.subprocess, "run", side_effect=other_targets):
            with self.assertRaisesRegex(ValueError, "required project and targets"):
                compiler.compile_component(self.root, "/fake/tool4d")

    @unittest.skipUnless(__import__("os").name == "posix", "symlink requires POSIX")
    def test_cleanup_does_not_follow_derived_data_symlink(self):
        outside = self.root / "sentinel-directory"
        outside.mkdir()
        sentinel = outside / "keep"
        sentinel.write_text("not compiler output")
        (self.project.parent / "DerivedData").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            compiler.compile_component(self.root, "/fake/tool4d")
        self.assertEqual(sentinel.read_text(), "not compiler output")
