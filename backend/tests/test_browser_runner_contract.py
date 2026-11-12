"""X10-018 runner policy regression tests, not browser/Android runtime proof."""
import unittest
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
# AppLab CI runs pytest from backend/ as well as the repo root; the
# repository-local scripts folder is not a pip-installed package.
sys.path.insert(0, str(ROOT))
from scripts.check_browser_runner_contract import (  # noqa: E402
    RunnerCompatibilityError, check_contract, check_host,
)


class BrowserRunnerContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (ROOT / ".github/workflows/live-emulator-self-test.yml").read_text()
        cls.package = json.loads((ROOT / "frontend/e2e/package.json").read_text())

    def test_pinned_runner_and_required_browser_suite(self):
        result = check_contract(self.workflow, self.package)
        self.assertEqual(result["runner"], "ubuntu-24.04")
        self.assertEqual(result["playwright"], "1.55.0")

    def test_future_runner_upgrade_requires_explicit_review(self):
        workflow = self.workflow.replace("runs-on: ubuntu-24.04", "runs-on: ubuntu-latest")
        self.assertNotEqual(workflow, self.workflow)
        with self.assertRaisesRegex(RunnerCompatibilityError, "UNSUPPORTED_BROWSER_RUNNER"):
            check_contract(workflow, self.package)

    def test_cannot_skip_browser_test_with_green_fake_scope(self):
        workflow = self.workflow.replace(
            "if: github.event_name != 'pull_request' || needs.scope.outputs.run == 'true'",
            "if: always()"
        )
        self.assertNotEqual(workflow, self.workflow)
        with self.assertRaisesRegex(RunnerCompatibilityError, "REQUIRED_SCOPE_GATE_CHANGED"):
            check_contract(workflow, self.package)

    def test_missing_real_browser_suite_rejected(self):
        workflow = self.workflow.replace("run: npm test", "run: echo skipped")
        self.assertNotEqual(workflow, self.workflow)
        with self.assertRaisesRegex(RunnerCompatibilityError, "BROWSER_E2E_REMOVED"):
            check_contract(workflow, self.package)

    def test_conditional_browser_step_rejected(self):
        marker = "      - name: Browser WebRTC video and input E2E"
        workflow = self.workflow.replace(
            marker, marker + "\n        if: \${{ false }}"
        )
        self.assertNotEqual(workflow, self.workflow)
        with self.assertRaisesRegex(
            RunnerCompatibilityError, "BROWSER_E2E_BYPASS_FORBIDDEN"
        ):
            check_contract(workflow, self.package)

    def test_continue_on_error_browser_step_rejected(self):
        marker = "      - name: Browser WebRTC video and input E2E"
        workflow = self.workflow.replace(
            marker, marker + "\n        continue-on-error: true"
        )
        self.assertNotEqual(workflow, self.workflow)
        with self.assertRaisesRegex(
            RunnerCompatibilityError, "BROWSER_E2E_BYPASS_FORBIDDEN"
        ):
            check_contract(workflow, self.package)

    def test_bumped_playwright_requires_review(self):
        package = dict(self.package)
        package["devDependencies"] = {"@playwright/test": "1.56.0"}
        with self.assertRaisesRegex(RunnerCompatibilityError, "PLAYWRIGHT_VERSION_REQUIRES_REVIEW"):
            check_contract(self.workflow, package)

    def test_valid_host_vs_future_or_non_ubuntu_release(self):
        check_host('ID=ubuntu\nVERSION_ID="24.04"\n')
        for release in ("ID=ubuntu\nVERSION_ID=26.04\n",
                        "ID=debian\nVERSION_ID=24.04\n",
                        "VERSION_ID=24.04\n", "ID=ubuntu\n"):
            with self.subTest(release=release), self.assertRaisesRegex(
                RunnerCompatibilityError, "UNSUPPORTED_HOST_RELEASE"
            ):
                check_host(release)


if __name__ == "__main__":
    unittest.main()
