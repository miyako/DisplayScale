import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WindowsHostContractTests(unittest.TestCase):
    def test_windows_override_preserves_every_common_feature_assertion(self):
        contract = json.loads((ROOT / "tests/host/contract.json").read_text(encoding="utf-8"))
        windows = contract["platforms"]["Windows"]["feature"]
        assertions = {item["path"]: item for item in windows["assertions"]}
        for item in contract["feature"]["assertions"]:
            if not item["path"].startswith("/monitors/"):
                self.assertEqual(assertions.get(item["path"]), item, item["path"])
        self.assertEqual(windows["caseCount"], 1)
        self.assertNotIn("cases", windows)
        self.assertEqual(windows["casesPath"], "/cases")
        self.assertTrue(windows["caseAssertions"])

    def test_common_execution_contract_retains_prelaunch_and_path_checks(self):
        contract = json.loads((ROOT / "tests/host/contract.json").read_text(encoding="utf-8"))
        assertions = {item["path"]: item for item in contract["execution"]["assertions"]}
        self.assertEqual(assertions["/rejectedArguments"]["length"], 9)
        self.assertEqual(assertions["/rejectedNul"]["length"], 3)
        self.assertTrue(assertions["/pathChecks"]["equals"])
        self.assertEqual(assertions["/quotedArguments"]["length"], 6)
