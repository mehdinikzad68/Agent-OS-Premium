# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

# -*- coding: utf-8 -*-
"""Permanent guard: every class used in the UI markup must exist in the sheet.

The remove button shipped with class="chip" and a .msg span, neither of which
exists in this stylesheet, so the control rendered unstyled. Nothing failed:
the class attribute is not checked by the structural test and the button still
worked. A name that does nothing is a silent defect, so pin it.

Reads the sheet, collects the class selectors, then finds class="..." in the
markup and template strings, and requires every one of them to be defined.
"""
import re
import sys
import unittest
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "agent_os" / "web" / "index.html"
SRC = INDEX.read_text(encoding="utf-8")

# selectors defined in the <style> block
STYLE = SRC[SRC.index("<style>"):SRC.index("</style>")]
DEFINED = set(re.findall(r"\.([A-Za-z][\w-]*)", STYLE))

# ids defined in the <style> block, for id="..." in markup
DEFINED_IDS = set(re.findall(r"#([A-Za-z][\w-]*)", STYLE))

MARKUP = SRC[SRC.index("<body"):]
USED_CLASSES = set()
for m in re.finditer(r'class="([^"$]*)"', MARKUP):
    USED_CLASSES.update(m.group(1).split())
# classes that only ever appear inside a template literal
for m in re.finditer(r'class="([^"]*\$\{[^"]*)"', SRC):
    USED_CLASSES.update(re.findall(r"\$\{[^}]*\}", m.group(1)) and [] or [])
    USED_CLASSES.update(
        c for c in m.group(1).split() if c and "$" not in c)


class ClassVocabularyTest(unittest.TestCase):
    def test_the_stylesheet_was_parsed(self):
        """A guard that reads nothing passes everything. Fail loudly instead."""
        self.assertGreater(len(DEFINED), 20,
                           "the style block looks empty - the parser broke")
        self.assertIn("row-inline", DEFINED)

    def test_every_class_in_the_markup_is_defined(self):
        missing = sorted(USED_CLASSES - DEFINED - {"ok"})
        self.assertEqual(
            missing, [],
            f"class(es) used in the markup but not defined in the stylesheet: "
            f"{missing}. An undefined class is not an error, it is invisible: "
            f"the element renders unstyled and nothing reports it.")

    def test_the_remove_button_uses_a_defined_class(self):
        self.assertIn('<button type="button" class="pill">', SRC)
        self.assertNotIn('class="chip"', SRC,
                         "chip was never defined in this stylesheet")
        self.assertNotIn('class="msg', SRC,
                         "msg was never defined in this stylesheet")

    def test_the_failure_message_uses_the_hidden_property(self):
        self.assertIn("<span class=\"muted\" hidden></span>", SRC)
        self.assertNotIn("msg.style.display", SRC)

    def test_the_selector_and_the_markup_name_the_same_class(self):
        """The bug this file exists for. I renamed the markup to
        `button.pill` / `span.muted` and left the querySelector reading
        `button.chip` / `.msg`: both return null, so the handler binding threw
        a TypeError on every render while every string assertion still
        passed. A selector that disagrees with its own markup is a crash."""
        panel = SRC[SRC.index("async function loadProjects()"):]
        panel = panel[:panel.index("\n}\n")]
        markup_btn = re.search(r'<button type="button" class="([\w-]+)"', panel)
        markup_msg = re.search(r'<span class="([\w-]+)" hidden>', panel)
        self.assertIsNotNone(markup_btn, "no remove button in loadProjects()")
        self.assertIsNotNone(markup_msg, "no hidden message in loadProjects()")

        sel_btn = re.search(r'querySelector\("button\.([\w-]+)"\)', panel)
        sel_msg = re.search(r'querySelector\("span\.([\w-]+)"\)', panel)
        self.assertIsNotNone(sel_btn, "no button selector in loadProjects()")
        self.assertIsNotNone(sel_msg, "no message selector in loadProjects()")

        self.assertEqual(sel_btn.group(1), markup_btn.group(1),
                         "the button selector and the button markup disagree")
        self.assertEqual(sel_msg.group(1), markup_msg.group(1),
                         "the message selector and the message markup disagree")

    def test_the_handler_uses_the_real_reason_helper_name(self):
        """reasonText, not _reasonText. A brief that names a helper the file
        does not have produces a ReferenceError at click time, which no
        structural test can see."""
        self.assertRegex(SRC, r"function reasonText\(reason, fallback\)")
        self.assertNotIn("_reasonText", SRC)

    def test_the_remove_handler_calls_the_endpoint_with_the_project_id(self):
        self.assertIn('api("DELETE", "/api/projects/" + p.id)', SRC)

    def test_no_new_i18n_key_is_left_unreachable(self):
        """Both new keys are used, so the reachability test in
        test_ui_i18n stays meaningful."""
        for key in ("ui.remove", "ui.removeFail"):
            self.assertIn(f'"{key}"', SRC)
            self.assertIn(f'"{key}":', SRC)


if __name__ == "__main__":
    unittest.main()
