# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Suite-health guards: a test that is never collected is not a test.

Review 2026-10-05 (T1): `test_oversized_body_rejected` sat at module scope
in test_api.py - flush left, outside every TestCase - so unittest's loader
never ran it while README/READINESS reported "413 ... pass". The body-cap
guarantee (A10) was in fact untested. The working tree since repaired the
test itself (it now lives in UiServingTest); this file keeps the CLASS of
defect from coming back: any `def test_*` defined at module level is dead
code, and the documented 413 test must exist as a real TestCase method.
"""

from __future__ import annotations

import pathlib
import unittest

TESTS_DIR = pathlib.Path(__file__).resolve().parent


class NoOrphanedTestFunctionsTest(unittest.TestCase):
    def test_no_module_level_test_functions_anywhere(self):
        """Any `def test_*` at column 0 is invisible to unittest's loader."""
        offenders = []
        for f in sorted(TESTS_DIR.glob("test_*.py")):
            for lineno, line in enumerate(
                f.read_text(encoding="utf-8").splitlines(), 1
            ):
                if line.startswith("def test_"):
                    offenders.append(f"{f.name}:{lineno}")
        self.assertEqual(
            offenders,
            [],
            "module-level `def test_*` found; unittest never collects these "
            "(the T1 defect): " + ", ".join(offenders),
        )

    def test_the_documented_413_test_is_a_real_method(self):
        """README/READINESS claim test_oversized_body_rejected passes - that
        claim must map to a method a TestCase actually collects."""
        src = (TESTS_DIR / "test_api.py").read_text(encoding="utf-8")
        self.assertIn(
            "    def test_oversized_body_rejected(self):",
            src,
            "the documented 413 body-cap test must be a method inside a "
            "TestCase, not a module-level orphan",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
