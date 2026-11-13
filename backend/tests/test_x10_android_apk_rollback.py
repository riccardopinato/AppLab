"""X10-032 offline safety tests; no emulator or Android install required."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/x10_android_apk_rollback.py"
spec = importlib.util.spec_from_file_location("x10_android_apk_rollback", SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def process(code=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class TestRollbackSafety(unittest.TestCase):
    def test_real_device_fails_before_uninstall(self):
        with patch.object(harness, "run", side_effect=[
            process(stdout="R9P99999\n"), process(stdout="0\n")
        ]):
            with self.assertRaisesRegex(RuntimeError, "REAL_DEVICE_FORBIDDEN"):
                harness.assert_emulator()

    def test_fails_closed_on_wrong_package(self):
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / "test.apk"
            apk.write_bytes(b"fixture")
            with patch.object(harness, "run", return_value=process(
                stdout="package: name='com.riccardopinato.agenda_per_anna' versionCode='101'")):
                with self.assertRaisesRegex(ValueError, "TEST_PACKAGE_OR_VERSION_MISMATCH"):
                    harness.apk_metadata(apk, 101, Path(d))

    def test_fails_closed_on_bad_signature(self):
        with tempfile.TemporaryDirectory() as d:
            apk = Path(d) / "test.apk"
            apk.write_bytes(b"fixture")
            with patch.object(harness, "run", side_effect=[
                process(stdout="package: name='dev.applab.selftest' versionCode='101'"),
                process(stdout="No certificate verified")]):
                with self.assertRaisesRegex(ValueError, "APK_SIGNATURE_NOT_VERIFIED"):
                    harness.apk_metadata(apk, 101, Path(d))

    def test_only_emulator_is_classified(self):
        with patch.object(harness, "run", side_effect=[
            process(stdout="emulator-5554\n"), process(stdout="1\n"),
            process(stdout="35\n"), process(stdout="google/sdk_gphone64_x86_64:35/test\n")
        ]):
            self.assertEqual(harness.assert_emulator()["serial_type"], "emulator")


if __name__ == "__main__":
    unittest.main()
