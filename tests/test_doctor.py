import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("display_scale_doctor", ROOT / "scripts/doctor.py")
doctor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(doctor)


class DoctorScopeTests(unittest.TestCase):
    def test_macos_is_a_production_feature_platform_with_universal_resources(self):
        with patch.object(doctor.platform, "system", return_value="Darwin"), \
                patch.object(doctor, "native_target", return_value="macos-arm64"):
            report = doctor.doctor(ROOT)
        self.assertEqual(report["resource_targets"], ["macos-x64", "macos-arm64", "windows-x64"])
        self.assertEqual(report["unsupported_backend_platforms"], [])
        self.assertFalse(report["local_development_only"])
        self.assertFalse(report["release_ready"])
        self.assertIn("lipo", [check["name"] for check in report["checks"]])

    def test_windows_is_not_a_development_only_platform(self):
        with patch.object(doctor.platform, "system", return_value="Windows"), \
                patch.object(doctor, "native_target", return_value="windows-x64"):
            report = doctor.doctor(ROOT)
        self.assertFalse(report["local_development_only"])
        self.assertFalse(report["release_ready"])
