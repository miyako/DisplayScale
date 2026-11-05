"""Parser/configuration regressions; synthetic outputs are not native runtime evidence."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("windows_runtime", ROOT / "scripts/check_windows_runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def dependencies(*names):
    return ("Microsoft dumpbin\n\nImage has the following dependencies:\n\n"
            + "\n".join("    " + name for name in names) + "\n\n  Summary\n    1000 .text\n")


class WindowsRuntimeTests(unittest.TestCase):
    def test_only_explicit_system_imports_are_accepted(self):
        result = runtime.dependency_names(dependencies("KERNEL32.dll", "USER32.dll", "SHCORE.dll"))
        self.assertEqual(result, ["kernel32.dll", "shcore.dll", "user32.dll"])
        for extra in ("VCRUNTIME140.dll", "MSVCP140.dll", "ucrtbase.dll", "custom.dll",
                      "api-ms-win-crt-runtime-l1-1-0.dll"):
            with self.subTest(extra=extra), self.assertRaisesRegex(ValueError, "unexpected"):
                runtime.dependency_names(dependencies("KERNEL32.dll", "USER32.dll", "SHCORE.dll", extra))

    def test_empty_incomplete_and_unrecognized_import_output_fails(self):
        for text in ("", "Summary", dependencies("KERNEL32.dll"),
                     dependencies("KERNEL32.dll", "USER32.dll", "SHCORE.dll").replace("  Summary", ""),
                     dependencies("KERNEL32.dll", "USER32.dll", "SHCORE.dll", "bad dependency text")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                runtime.dependency_names(text)

    def test_delay_imports_cannot_hide_dynamic_runtime_dependencies(self):
        text = dependencies("KERNEL32.dll", "USER32.dll", "SHCORE.dll").replace(
            "  Summary", "Image has the following delay load dependencies:\n  VCRUNTIME140.dll\n  Summary")
        with self.assertRaisesRegex(ValueError, "unexpected"):
            runtime.dependency_names(text)

    def test_actual_object_directives_must_be_retail_static(self):
        self.assertEqual(runtime.default_libraries(
            '/DEFAULTLIB:LIBCMT /DEFAULTLIB:"libcpmt.lib" /DEFAULTLIB:OLDNAMES'),
            ["libcmt", "libcpmt", "oldnames"])
        for directives in ("", "/DEFAULTLIB:MSVCRT", "/DEFAULTLIB:LIBCMTD",
                           "/DEFAULTLIB:LIBCMT /DEFAULTLIB:MSVCPRT",
                           "/DEFAULTLIB:LIBCMT /DEFAULTLIB:ucrt"):
            with self.subTest(directives=directives), self.assertRaises(ValueError):
                runtime.default_libraries(directives)

    def test_release_x64_project_cannot_select_dll_or_debug_crt(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "display-scale.vcxproj"
            for selected in ("MultiThreaded", "MultiThreadedDLL", "MultiThreadedDebug", ""):
                project.write_text(
                    '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">'
                    '<ItemDefinitionGroup Condition="\'$(Configuration)|$(Platform)\'==\'Release|x64\'">'
                    '<ClCompile><RuntimeLibrary>' + selected + '</RuntimeLibrary></ClCompile>'
                    '</ItemDefinitionGroup></Project>', encoding="utf-8")
                if selected == "MultiThreaded":
                    self.assertEqual(runtime.runtime_selection(project), selected)
                else:
                    with self.subTest(selected=selected), self.assertRaises(ValueError):
                        runtime.runtime_selection(project)

    def test_debug_configuration_cannot_approve_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary).resolve() / "display-scale.vcxproj"
            project.write_text(
                '<Project><ItemDefinitionGroup Condition="\'$(Configuration)|$(Platform)\'==\'Debug|x64\'">'
                '<ClCompile><RuntimeLibrary>MultiThreaded</RuntimeLibrary></ClCompile>'
                '</ItemDefinitionGroup></Project>', encoding="utf-8")
            with self.assertRaises(ValueError):
                runtime.runtime_selection(project)

    def test_non_native_host_is_not_import_inspection_evidence(self):
        with patch.object(runtime, "native_target", return_value="macos-arm64"), \
                patch.object(runtime, "load_config") as config:
            with self.assertRaisesRegex(ValueError, "native Windows x64"):
                runtime.inspect(ROOT)
            config.assert_not_called()

    def test_dumpbin_uses_the_actual_configured_compiler_not_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            configuration = root / "CMakeFiles/4.0/CMakeCXXCompiler.cmake"
            configuration.parent.mkdir(parents=True)
            compiler = root / "MSVC/cl.exe"
            compiler.parent.mkdir()
            compiler.write_bytes(b"synthetic")
            tool = compiler.with_name("dumpbin.exe")
            tool.write_bytes(b"synthetic")
            configuration.write_text(
                'set(CMAKE_CXX_COMPILER "' + compiler.as_posix() + '")\n', encoding="utf-8")
            self.assertEqual(runtime.dumpbin_path(root), tool)
            tool.unlink()
            with self.assertRaisesRegex(ValueError, "sibling dumpbin"):
                runtime.dumpbin_path(root)
