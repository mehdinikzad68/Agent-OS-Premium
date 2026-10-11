# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

# -*- coding: utf-8 -*-
"""The approval card must SHOW the command it authorizes.

F1 put `command` into ApprovalScope and into the API response. That is the
data half. This pins the half a human actually experiences: the pending-approval
card is where the Approve button lives, and before this change it named only
the executor and the actions. Approving was therefore a decision made blind -
the grant said "run_tests on subprocess-executor" while the effect was whatever
argv the job carried.

These are source assertions, which is the weakest kind of test in this repo -
a string check cannot see a crash. That is the reason the F1 proof script
drives the real server; this file only keeps the UI from silently losing the
line again. Kept here rather than folded into test_ui_i18n.py so the reason each
assertion exists stays attached to it.
"""
import pathlib
import re
import unittest

HTML = (
    pathlib.Path(__file__).resolve().parent.parent
    / "agent_os" / "web" / "index.html"
).read_text(encoding="utf-8")


class ApprovalCardShowsTheCommandTest(unittest.TestCase):
    def test_the_pending_approval_renderer_reads_the_command(self):
        self.assertIn("a.scope.command", HTML,
                      "the approval card never reads scope.command")

    def test_the_command_is_rendered_into_the_card(self):
        # A test asserting only that the property is READ would pass even if
        # the value were read and thrown away.
        self.assertIn("cmd.join", HTML,
                      "the command is read but never shown")

    def test_the_rendered_command_is_escaped(self):
        # The command is caller-supplied and reaches innerHTML. This is the
        # same class as the 28 unescaped interpolations fixed in 99a345b; a
        # regression here would re-open it through a new door.
        i = HTML.find("const cmdHtml =")
        self.assertGreater(i, 0)
        window = HTML[i:i + 400]
        self.assertIn("escapeHtml", window,
                      "the command is interpolated without escaping")

    def test_technical_text_stays_ltr(self):
        # Persian is the default UI direction; an argv rendered under it would
        # be reordered by the bidi algorithm, so a path could read differently
        # from what runs. Isolate + ltr is the fix, and both parts are needed.
        self.assertRegex(HTML, r"\.tech\s*\{[^}]*direction:\s*ltr")
        self.assertRegex(HTML, r"\.tech\s*\{[^}]*unicode-bidi:\s*isolate")

    def test_the_command_line_uses_the_tech_class(self):
        # Anchor on the DECLARATION, not on the first mention: the name also
        # appears in the comment above, and searching from there landed the
        # 300-character window inside the comment instead of the code.
        i = HTML.find("const cmdHtml =")
        self.assertGreater(i, 0, "the command line is never built")
        self.assertIn('class="m tech"', HTML[i:i + 200],
                      "the command is not marked as technical LTR content")

    def test_the_interpolated_variable_is_escaped_too(self):
        # Added because the repo's own escape test caught this: the scanner
        # looks for ${expr} inside innerHTML and cannot see that a variable was
        # escaped where it was built, so a raw ${cmdHtml} reads as unescaped.
        # The interpolated name must therefore be the escaped one, and
        # cmdSafe must be an allowlisted name there for the same reason.
        self.assertIn("${cmdSafe}", HTML)
        i = HTML.find("const cmdSafe = escapeHtml(")
        self.assertGreater(i, 0, "the command line is not escaped at construction")
        i2 = HTML.find("div.innerHTML = `<div class=\"t\">${t(\"approvals.forJob\")}")
        self.assertGreater(i2, 0, "the approval card renderer moved")
        self.assertNotIn("${cmdHtml}", HTML[i2:i2 + 900],
                         "the unescaped command line still reaches innerHTML")

    def test_the_escape_allowlist_names_it_rather_than_hiding_it(self):
        # The security scanner allowlists variable names it cannot follow. If
        # cmdSafe were dropped from that list the scanner would start
        # reporting it, which is the intended alarm, so the entry has to exist
        # AND the variable has to be escapeHtml(...) of a literal-built block.
        i18n = (pathlib.Path(__file__).resolve().parent / "test_ui_i18n.py")
        src = i18n.read_text(encoding="utf-8")
        self.assertIn('"cmdSafe"', src,
                      "cmdSafe reaches innerHTML but is not on the escape allowlist")

    def test_a_job_without_a_command_renders_no_command_line(self):
        # The pre-fix approval rows decode to None, and an approval for a
        # command-less job is legitimate. Rendering `null` or an empty box
        # would be noise; a check that a.scope.command is an array is what
        # keeps that case quiet.
        self.assertRegex(HTML, r"Array\.isArray\(a\.scope\.command\)")

    def test_the_approve_button_is_still_on_the_same_card(self):
        # The command must not have displaced the controls. If someone later
        # restructures the card, the decision has to remain one click away.
        i = HTML.find("const cmdHtml =")
        window = HTML[i:i + 1200]
        self.assertIn("'granted'", window)
        self.assertIn("'denied'", window)


class CommandIsNotTheOnlyThingShownTest(unittest.TestCase):
    """Adding the command must not REPLACE what was already there."""

    # The window has to reach the innerHTML assignment, which sits further down
    # than 400 characters. Too short a window produced a failure that looked
    # like the actions had been removed when they were merely out of range.
    W = 1200

    def _card(self):
        # Anchor on the declaration, not the first mention - the identifier
        # also occurs in the explanatory comment above it.
        i = HTML.find("const cmdHtml =")
        self.assertGreater(i, 0, "the command is not read at all")
        return HTML[i:i + self.W]

    def test_the_executor_is_still_shown(self):
        self.assertIn("a.scope.executor", self._card())

    def test_the_actions_are_still_shown(self):
        self.assertIn("a.scope.actions", self._card())


if __name__ == "__main__":
    unittest.main()
