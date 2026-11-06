import sys
import ctypes
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def json_line(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


ERROR = json_line({"protocol": 2, "error": {
    "code": "INVALID_ARGUMENTS", "message": "expected monitors or --version"}})


class CppCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        selected = os.environ.get("TEST_CLI_LANGUAGE")
        if selected not in (None, "none", "cpp"):
            raise RuntimeError("DisplayScale requires TEST_CLI_LANGUAGE=cpp or none")
        if selected == "none":
            raise unittest.SkipTest("CLI toolchains disabled by TEST_CLI_LANGUAGE=none")
        config = json.loads((ROOT / "template.json").read_text(encoding="utf-8"))
        if config["language"] != "cpp":
            raise RuntimeError("DisplayScale requires C++")
        if shutil.which("cmake") is None:
            raise RuntimeError("missing selected CMake toolchain")
        compiler = None
        if os.name != "nt":
            compiler = next((shutil.which(tool) for tool in ("c++", "g++", "clang++")
                             if shutil.which(tool)), None)
            if compiler is None:
                raise RuntimeError("missing selected C++17 compiler")
        scratch = tempfile.TemporaryDirectory(prefix=".cli-test 世界 path ", dir=ROOT / "tests")
        cls.addClassCleanup(scratch.cleanup)
        root = Path(scratch.name)
        source = root / "source"
        shutil.copytree(ROOT / "cli", source)
        build = root / "build"
        cls.configure_options = (["-A", "x64"] if os.name == "nt" else
                                 ["-DCMAKE_CXX_COMPILER=" + compiler])
        commands = [
            ["cmake", "-S", str(source), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
             "-DBUILD_TESTING=ON", *cls.configure_options],
            ["cmake", "--build", str(build), "--config", "Release"],
        ]
        for command in commands:
            result = subprocess.run(command, capture_output=True, timeout=180)
            if result.returncode:
                raise RuntimeError("build failed: " + repr(command) + "\n" +
                                   (result.stdout + result.stderr).decode("utf-8", errors="replace"))
        name = config["cli"] + (".exe" if os.name == "nt" else "")
        built = build / name
        if not built.exists():
            built = build / "Release" / name
        destination = root / "executables with spaces 世界"
        destination.mkdir()
        cls.executable = destination / name
        shutil.copy2(built, cls.executable)
        echo_name = "display-scale-test-echo" + (".exe" if os.name == "nt" else "")
        built_echo = build / echo_name
        if not built_echo.exists():
            built_echo = build / "Release" / echo_name
        cls.echo_executable = destination / echo_name
        shutil.copy2(built_echo, cls.echo_executable)
        cls.build = build
        cls.source = source
        cls.root = root

    def run_cli(self, arguments):
        return subprocess.run([os.fspath(self.executable), *arguments],
                              capture_output=True, timeout=20)

    def assert_result(self, arguments, status, stdout, stderr):
        result = self.run_cli(arguments)
        self.assertEqual(result.returncode, status, result.stderr)
        self.assertEqual(result.stdout, stdout)
        self.assertEqual(result.stderr, stderr)

    def test_version(self):
        self.assert_result(["--version"], 0, b'{"protocol":2,"version":"0.1.0"}\n', b"")

    def test_pure_backend(self):
        result = subprocess.run(["ctest", "--test-dir", str(self.build), "-C", "Release",
                                 "--output-on-failure"], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode("utf-8"))

    def test_test_only_echo(self):
        arguments = [
            "", "世界 café 😀", 'a"b\\c', " leading and trailing ", "\\",
            "line\nbreak", "\t\r\b\f", "--version", "monitors",
            "$(echo not-executed); `echo nope`", str(self.executable.parent),
            "".join(chr(value) for value in range(1, 32)),
            "\u007f\u0080\u07ff\u0800\uffff\U0010ffff",
        ]
        for values in ([], arguments):
            result = subprocess.run([str(self.echo_executable), *values],
                                    capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(result.stdout, json_line({"protocol": 1, "arguments": values}))
        malformed = ([b"\xed\xa0\x80"] if os.name == "posix" else ["\ud800"])
        result = subprocess.run([str(self.echo_executable), *malformed],
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, json_line({"protocol": 2, "error": {
            "code": "INVALID_ARGUMENTS", "message": "arguments must be valid UTF-8"}}))

    def test_production_build_excludes_helpers(self):
        build = self.root / "production-build"
        for command in [
            ["cmake", "-S", str(self.source), "-B", str(build),
             "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF", *self.configure_options],
            ["cmake", "--build", str(build), "--config", "Release"],
        ]:
            result = subprocess.run(command, capture_output=True, timeout=180)
            self.assertEqual(result.returncode, 0,
                             (result.stdout + result.stderr).decode("utf-8", errors="replace"))
        for name in ("display-scale-test-echo", "display-scale-unit-tests"):
            self.assertFalse(list(build.rglob(name + (".exe" if os.name == "nt" else ""))))
        self.assertFalse((build / "CTestTestfile.cmake").exists())

    def test_contract_vectors(self):
        contract = json.loads((ROOT / "tests/cli-contract.json").read_text(encoding="utf-8"))
        self.assertEqual(contract["schema"], 1)
        target = platform.system()
        version = json.loads((ROOT / "template.json").read_text(encoding="utf-8"))["version"]
        for case in contract["cases"]:
            if "platforms" in case and target not in case["platforms"]:
                continue
            with self.subTest(arguments=case["args"]):
                result = self.run_cli(case["args"])
                self.assertEqual(result.returncode, case["exitCode"], result.stderr)
                for stream in ("stdout", "stderr"):
                    actual = getattr(result, stream)
                    if stream + "Pattern" in case:
                        self.assertIsNotNone(re.fullmatch(case[stream + "Pattern"],
                                                         actual.decode("utf-8")))
                    else:
                        expected = case[stream]
                        if isinstance(expected, dict):
                            expected = json_line(json.loads(json.dumps(expected).replace(
                                "$VERSION", version)))
                        else:
                            expected = expected.encode("utf-8")
                        self.assertEqual(actual, expected)

    def test_invalid_arguments(self):
        for arguments in [
            [], [""], ["unknown"], ["greet", "--name", "World"],
            ["monitors", "extra"], ["--version", "extra"], ["--version", "--version"],
            ["MONITORS"], ["--monitors"], ["monitors", "--version"],
            ["世界 café 😀"], ['"quoted" \\backslash; \'$()\''],
            ["echo"], ["test"], ["monitors", "\t\r\b\f\n"],
        ]:
            with self.subTest(arguments=arguments):
                self.assert_result(arguments, 2, b"", ERROR)

    @unittest.skipUnless(os.name == "posix", "raw arguments require POSIX")
    def test_malformed_utf8(self):
        for value in [
            b"\x80", b"\xff", b"\xc0\xaf", b"\xc1\xbf", b"\xc2",
            b"\xe2\x82", b"\xe2(\xa1", b"\xe0\x80\x80", b"\xed\xa0\x80",
            b"\xf0\x80\x80\x80", b"\xf4\x90\x80\x80", b"\xf5\x80\x80\x80",
            b"\xf8\x88\x80\x80\x80", b"valid\xfe",
        ]:
            for arguments in ([value], [b"monitors", value], [b"--version", value]):
                with self.subTest(arguments=arguments):
                    self.assert_result(arguments, 2, b"", ERROR)

    @unittest.skipUnless(os.name == "nt", "UTF-16 argv requires Windows")
    def test_malformed_utf16(self):
        for value in ["\ud800", "\udfff", "valid\ud800"]:
            self.assert_result([value], 2, b"", ERROR)

    @unittest.skipUnless(sys.platform == "darwin", "macOS CoreGraphics backend")
    def test_native_macos_topology(self):
        result = self.run_cli(["monitors"])
        if result.returncode == 3 and b'"NO_MONITORS"' in result.stderr:
            self.skipTest("no active macOS display (headless session)")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout.count(b"\n"), 1)
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(payload), {"protocol", "platform", "monitors"})
        self.assertEqual(payload["protocol"], 2)
        self.assertEqual(payload["platform"], "macos")
        monitors = payload["monitors"]
        self.assertTrue(monitors)
        self.assertEqual(monitors, sorted(monitors, key=lambda m: (not m["primary"], m["device"])))
        self.assertEqual(sum(1 for monitor in monitors if monitor["primary"]), 1)
        for monitor in monitors:
            self.assertEqual(set(monitor), {"device", "primary", "bounds", "backingPixels",
                                            "nativePixels", "backingScalePercent", "scalePercent"})
            bounds = monitor["bounds"]
            points = bounds["right"] - bounds["left"]
            self.assertGreater(points, 0)
            self.assertGreater(bounds["bottom"], bounds["top"])
            for key in ("backingPixels", "nativePixels"):
                self.assertEqual(set(monitor[key]), {"width", "height"})
                self.assertTrue(all(type(v) is int and v > 0 for v in monitor[key].values()))
            self.assertAlmostEqual(monitor["backingScalePercent"],
                                   monitor["backingPixels"]["width"] / points * 100, delta=1e-9)
            self.assertAlmostEqual(monitor["scalePercent"],
                                   monitor["nativePixels"]["width"] / points * 100, delta=1e-9)

    @unittest.skipUnless(os.name == "nt", "real Windows topology required")
    def test_native_topology(self):
        self.assertEqual(platform.machine().lower(), "amd64", "requires native x64")
        before = windows_topology()
        result = self.run_cli(["monitors"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.endswith(b"\n"))
        self.assertEqual(result.stdout.count(b"\n"), 1)
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(set(payload), {"protocol", "platform", "monitors"})
        self.assertIs(type(payload["protocol"]), int)
        self.assertEqual(payload["protocol"], 2)
        self.assertEqual(payload["platform"], "windows")
        after = windows_topology()
        self.assertEqual(before, after, "topology changed during native smoke test")
        monitors = payload["monitors"]
        self.assertTrue(monitors)
        self.assertEqual(len(monitors), len(before))
        self.assertEqual(monitors, sorted(monitors, key=lambda m: (not m["primary"], m["device"])))
        for monitor in monitors:
            self.assertEqual(set(monitor), {"device", "primary", "bounds", "dpi", "scalePercent"})
            self.assertIs(type(monitor["device"]), str)
            self.assertIs(type(monitor["primary"]), bool)
            self.assertIs(type(monitor["dpi"]), int)
            self.assertGreater(monitor["dpi"], 0)
            self.assertIn(type(monitor["scalePercent"]), (int, float))
            self.assertAlmostEqual(monitor["scalePercent"], monitor["dpi"] / 96 * 100,
                                   delta=1e-9)
            self.assertEqual(set(monitor["bounds"]), {"left", "top", "right", "bottom"})
            for coordinate in monitor["bounds"].values():
                self.assertIs(type(coordinate), int)
            expected = before[monitor["device"]]
            self.assertEqual({key: monitor[key] for key in ("primary", "bounds", "dpi")}, expected)


def windows_topology():
    """Independent ctypes observation with monitor-local, PMv2-aware HWNDs."""
    from ctypes import wintypes as w
    user = ctypes.WinDLL("user32", use_last_error=True)
    context = ctypes.c_void_p
    user.SetThreadDpiAwarenessContext.argtypes = [context]
    user.SetThreadDpiAwarenessContext.restype = context
    user.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   w.HWND, w.HMENU, w.HINSTANCE, ctypes.c_void_p]
    user.CreateWindowExW.restype = w.HWND
    user.MonitorFromWindow.argtypes = [w.HWND, w.DWORD]
    user.MonitorFromWindow.restype = w.HANDLE
    user.GetDpiForWindow.argtypes = [w.HWND]
    user.GetDpiForWindow.restype = w.UINT
    user.DestroyWindow.argtypes = [w.HWND]
    user.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    user.GetWindowRect.restype = w.BOOL
    user.GetWindowDpiAwarenessContext.argtypes = [w.HWND]
    user.GetWindowDpiAwarenessContext.restype = context
    user.AreDpiAwarenessContextsEqual.argtypes = [context, context]
    user.AreDpiAwarenessContextsEqual.restype = w.BOOL

    class Info(ctypes.Structure):
        _fields_ = [("size", w.DWORD), ("bounds", w.RECT), ("work", w.RECT),
                    ("flags", w.DWORD), ("device", w.WCHAR * 32)]

    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HANDLE, w.HDC,
                                     ctypes.POINTER(w.RECT), w.LPARAM)
    user.GetMonitorInfoW.argtypes = [w.HANDLE, ctypes.POINTER(Info)]
    user.GetMonitorInfoW.restype = w.BOOL
    user.EnumDisplayMonitors.argtypes = [w.HDC, ctypes.POINTER(w.RECT), callback_type, w.LPARAM]
    user.EnumDisplayMonitors.restype = w.BOOL
    previous = user.SetThreadDpiAwarenessContext(context(-4))
    if not previous:
        raise AssertionError("cannot establish PMv2 test context")
    monitors, failures = {}, []

    def callback(handle, _dc, _rect, _data):
        window = None
        try:
            info = Info()
            info.size = ctypes.sizeof(info)
            if not user.GetMonitorInfoW(handle, ctypes.byref(info)):
                raise AssertionError("GetMonitorInfoW failed")
            b = info.bounds
            window = user.CreateWindowExW(0x08000080, "STATIC", "", 0x80000000,
                                         (b.left + b.right) // 2, (b.top + b.bottom) // 2,
                                         1, 1, None, None, None, None)
            if not window:
                raise AssertionError("CreateWindowExW failed")
            if user.MonitorFromWindow(window, 0) != handle:
                raise AssertionError("probe monitor mismatch")
            actual = w.RECT()
            if not user.GetWindowRect(window, ctypes.byref(actual)):
                raise AssertionError("GetWindowRect failed")
            if not (b.left <= actual.left < actual.right <= b.right and
                    b.top <= actual.top < actual.bottom <= b.bottom):
                raise AssertionError("probe physical bounds outside monitor")
            if not user.AreDpiAwarenessContextsEqual(
                    user.GetWindowDpiAwarenessContext(window), context(-4)):
                raise AssertionError("probe awareness mismatch")
            dpi = user.GetDpiForWindow(window)
            if not dpi:
                raise AssertionError("GetDpiForWindow failed")
            monitors[info.device] = {"primary": bool(info.flags & 1),
                                     "bounds": {key: getattr(b, key)
                                                for key in ("left", "top", "right", "bottom")},
                                     "dpi": dpi}
            return True
        except Exception as error:
            failures.append(error)
            return False
        finally:
            if window and not user.DestroyWindow(window):
                failures.append(AssertionError("DestroyWindow failed"))

    callback_function = callback_type(callback)
    try:
        success = user.EnumDisplayMonitors(None, None, callback_function, 0)
        if failures:
            raise failures[0]
        if not success or not monitors:
            raise AssertionError("native smoke requires actual display monitors")
        return monitors
    finally:
        if not user.SetThreadDpiAwarenessContext(previous):
            raise AssertionError("cannot restore test context")


if __name__ == "__main__":
    unittest.main()
