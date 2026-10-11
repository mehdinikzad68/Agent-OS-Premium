# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""M4 (B2): shared evidence detection - framework summaries first, the
original generic markers preserved as the compatibility fallback."""

from __future__ import annotations

import unittest

from agent_os.evidence import detect_test_report


class FrameworkSummaryFirstTest(unittest.TestCase):
    def test_pytest_summary_is_detected(self):
        out = detect_test_report(
            "collected 3 items\n\n== 3 passed in 0.10s ==\n", "", 0
        )
        self.assertTrue(out.startswith("detected framework summary"), out)
        self.assertIn("3 passed", out)

    def test_unittest_ok_line_is_detected(self):
        out = detect_test_report("Ran 3 tests in 0.001s\n\nOK\n", "", 0)
        self.assertTrue(out.startswith("detected framework summary"), out)

    def test_generic_markers_still_work(self):
        # f1_proof's calc.py prints exactly this; the fallback must not regress.
        out = detect_test_report("9 tests passed\n", "", 0)
        self.assertTrue(out.startswith("detected test signal"), out)
        self.assertIn("9 tests passed", out)

    def test_another_generic_marker(self):
        out = detect_test_report("all green: 5 passed in 0.0s\n", "", 0)
        self.assertTrue(out, "generic fallback missed a passing-looking line")

    def test_nonzero_exit_is_never_a_report(self):
        self.assertEqual(detect_test_report("== 3 passed in 0.1s ==", "", 1), "")

    def test_no_signal(self):
        self.assertEqual(detect_test_report("something happened", "", 0), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
