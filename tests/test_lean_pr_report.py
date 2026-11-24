"""Targeted contract tests for non-blocking Lean diff metrics."""
import unittest

from scripts.lean_pr_report import classify, parse_numstat, report


class LeanPrReportTests(unittest.TestCase):
    def test_parses_normal_and_binary(self):
        entries = parse_numstat(b"5\t2\tsrc/a.dart\0-\t-\tassets/photo.png\0")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["added"], 5)
        self.assertTrue(entries[1]["binary"])
        self.assertIsNone(entries[1]["deleted"])

    def test_rejects_malformed_record(self):
        with self.assertRaises(ValueError):
            parse_numstat(b"n/a\t2\ta.dart\0")

    def test_counts_generated_separately_and_does_not_infer_pass(self):
        entries = parse_numstat(
            b"15\t5\tlib/main.dart\0"
            b"100\t0\tlib/main.g.dart\0"
            b"3\t0\ttests/unit_test.py\0"
            b"2\t1\tpubspec.yaml\0"
        )
        data = report(entries, "abc", "def")
        self.assertEqual(data["files_changed"], 4)
        self.assertEqual(data["files_excluding_generated_and_lock"], 3)
        self.assertEqual(data["added_lines"], 20)
        self.assertEqual(data["deleted_lines"], 6)
        self.assertEqual(data["test_files_touched"], ["tests/unit_test.py"])
        self.assertEqual(data["dependency_manifests_touched"], ["pubspec.yaml"])
        self.assertEqual(data["test_results"], "NOT_VERIFIED")
        self.assertEqual(data["reuse"], "NOT_INFERABLE_FROM_DIFF")

    def test_classification(self):
        self.assertIn("generated_or_lockfile", classify("web/package-lock.json"))
        self.assertIn("test", classify("lib/widgets/foo_test.dart"))


if __name__ == "__main__":
    unittest.main()
