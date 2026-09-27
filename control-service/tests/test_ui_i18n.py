"""UI i18n tests for the offline mission-control console.

The console is a single self-contained index.html (under agent_os/web) with an
inline message catalog. It must:
- be present and valid UTF-8,
- carry no remote dependency (no CDN, no http/https script/stylesheet),
  so it works on an air-gapped machine,
- declare lang/dir on the <html> element and keep the LTR/monospace lane for
  machine-readable output (event feed, timestamps, diffs),
- expose a complete catalog for BOTH languages: every key present in one
  language must exist in the other, so no UI string can silently fall back.

Standard library only.
"""

from __future__ import annotations

import pathlib
import re
import unittest

HTML_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "agent_os"
    / "web"
    / "index.html"
)

# Static landmark markup must carry a data-i18n hook rather than a hard-coded
# Persian literal, so it can be re-rendered on a language switch.
STATIC_HOOKS = [
    "conn.connecting",
    "auth.connect",
    "sys.status",
    "mission.new",
    "mission.create",
    "mission.list",
    "mission.detail",
    "mission.selectOne",
    "job.detail",
    "approvals.box",
    "feed.title",
]

ATTR_HOOKS = [
    "placeholder:auth.tokenPlaceholder",
    "placeholder:mission.titlePlaceholder",
]


def _catalog(html: str, lang: str) -> dict:
    """Extract the key/value pairs of one language block from the inline catalog."""
    m = re.search(
        r"\n  " + lang + r":\s*\{(.*?)\n  \},", html, re.DOTALL
    )
    if not m:
        raise AssertionError(f"catalog block for language {lang!r} not found")
    return dict(re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', m.group(1)))


class UiI18nTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_bytes = HTML_PATH.read_bytes()
        cls.html = cls.raw_bytes.decode("utf-8")

    # -- integrity -----------------------------------------------------

    def test_ui_exists_and_offline(self):
        """Assert the file exists, is valid UTF-8, and has no remote assets."""
        self.assertTrue(HTML_PATH.exists(), f"UI file missing at {HTML_PATH}")
        self.assertGreater(len(self.html), 0)

        script_srcs = re.findall(
            r"""<script\b[^>]*?\bsrc\s*=\s*['"]([^'"]*)['"]""",
            self.html,
            re.IGNORECASE,
        )
        for src in script_srcs:
            self.assertFalse(
                src.strip().lower().startswith(("http://", "https://", "//")),
                f"External script source found: {src}",
            )

        for link in re.findall(r"<link\b[^>]*>", self.html, re.IGNORECASE):
            if re.search(r"""\brel\s*=\s*['"]\s*stylesheet\s*['"]""", link, re.IGNORECASE):
                href = re.search(r"""\bhref\s*=\s*['"]([^'"]*)['"]""", link, re.IGNORECASE)
                if href:
                    self.assertFalse(
                        href.group(1).strip().lower().startswith(
                            ("http://", "https://", "//")
                        ),
                        f"External stylesheet found: {href.group(1)}",
                    )

        head = re.search(r"<head>(.*?)</head>", self.html, re.DOTALL | re.IGNORECASE)
        if head:
            for cdn in ["cdnjs", "jsdelivr", "unpkg", "googleapis", "bootstrapcdn"]:
                self.assertNotIn(cdn, head.group(1).lower(), f"CDN '{cdn}' in <head>")

    # -- bilingual contract --------------------------------------------

    def test_catalog_has_both_languages(self):
        """Assert the inline catalog defines both `en` and `fa` blocks."""
        en = _catalog(self.html, "en")
        fa = _catalog(self.html, "fa")
        self.assertGreater(len(en), 0, "English catalog is empty")
        self.assertGreater(len(fa), 0, "Persian catalog is empty")

    def test_no_missing_translation(self):
        """Assert no key exists in one language and is absent from the other."""
        en = _catalog(self.html, "en")
        fa = _catalog(self.html, "fa")
        missing_fa = sorted(set(en) - set(fa))
        missing_en = sorted(set(fa) - set(en))
        self.assertEqual(missing_fa, [], f"keys missing Persian translation: {missing_fa}")
        self.assertEqual(missing_en, [], f"keys missing English translation: {missing_en}")

    def test_no_empty_translation(self):
        """Assert no catalog value is blank in either language."""
        for lang in ("en", "fa"):
            for key, value in _catalog(self.html, lang).items():
                self.assertTrue(value.strip(), f"empty value for {lang}:{key}")

    def test_static_markup_uses_i18n_hooks(self):
        """Assert static landmark text is hook-driven, not a hard-coded literal."""
        for key in STATIC_HOOKS:
            self.assertIn(
                f'data-i18n="{key}"',
                self.html,
                f"static node missing data-i18n hook for {key}",
            )
        for spec in ATTR_HOOKS:
            self.assertIn(
                f'data-i18n-attr="{spec}"',
                self.html,
                f"static attribute missing data-i18n-attr hook for {spec}",
            )

    def test_lang_and_dir_present(self):
        """Assert the <html> element declares both lang and dir."""
        tag = re.search(r"<html\b([^>]*)>", self.html, re.IGNORECASE)
        self.assertIsNotNone(tag, "<html> tag not found")
        self.assertIsNotNone(
            re.search(r"""\blang\s*=\s*['"][^'"]+['"]""", tag.group(1), re.IGNORECASE),
            "missing lang attribute on <html>",
        )
        self.assertIsNotNone(
            re.search(r"""\bdir\s*=\s*['"][^'"]+['"]""", tag.group(1), re.IGNORECASE),
            "missing dir attribute on <html>",
        )

    def test_persian_is_rtl_and_english_is_ltr(self):
        """Assert setLang maps fa->rtl and en->ltr, the owner's UI requirement."""
        self.assertRegex(
            self.html,
            r"""LANG\s*===\s*["']fa["']\s*\?\s*["']rtl["']\s*:\s*["']ltr["']""",
            "setLang must map fa to rtl and anything else to ltr",
        )

    def test_default_language_is_declared(self):
        """Assert DEFAULT_LANG is a language the catalog actually defines."""
        m = re.search(r"""const\s+DEFAULT_LANG\s*=\s*["']([a-z]{2})["']""", self.html)
        self.assertIsNotNone(m, "DEFAULT_LANG not declared")
        self.assertIn(
            m.group(1),
            _catalog(self.html, "en") and ("en", "fa"),
            f"DEFAULT_LANG {m.group(1)!r} is not a catalog language",
        )

    def test_apply_i18n_is_called_on_boot(self):
        """Assert the static markup is translated on load, not left empty."""
        self.assertIn("applyI18n();", self.html, "applyI18n() is never called")

    # -- technical content stays LTR + monospace ------------------------

    def test_technical_diff_code_styles(self):
        """Assert monospace feed and an LTR lane for timestamps."""
        feed = re.search(r"\.feed\s*\{([^}]*)\}", self.html, re.IGNORECASE)
        self.assertIsNotNone(feed, "CSS rule for .feed not found")
        self.assertIn("monospace", feed.group(1).lower(), ".feed must use a monospace font")

        ts = re.search(r"\.feed\s+\.ts\s*\{([^}]*)\}", self.html, re.IGNORECASE)
        self.assertIsNotNone(ts, "CSS rule for .feed .ts not found")
        self.assertTrue(
            re.search(r"float\s*:\s*left", ts.group(1), re.IGNORECASE)
            or re.search(r"direction\s*:\s*ltr", ts.group(1), re.IGNORECASE),
            "event timestamp must keep an LTR lane (float:left or direction:ltr)",
        )


if __name__ == "__main__":
    unittest.main()
