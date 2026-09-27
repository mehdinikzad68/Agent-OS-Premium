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


    # -- step 2-p: runtime strings go through t() ------------------------

    def _script(self) -> str:
        m = re.search(r"<script>([\s\S]*?)</script>", self.html)
        self.assertIsNotNone(m, "no <script> block found")
        return m.group(1)

    def _catalog_span(self, js: str) -> tuple[int, int]:
        """Line range of the inline catalog, so it can be excluded."""
        lines = js.split("\n")
        start = next(
            (i for i, l in enumerate(lines) if l.startswith("const I18N = {")), -1
        )
        self.assertNotEqual(start, -1, "const I18N not found")
        end = next(
            (i for i, l in enumerate(lines[start:], start) if l.strip() == "};"), -1
        )
        self.assertNotEqual(end, -1, "end of const I18N not found")
        return start, end

    def test_no_persian_literal_outside_the_catalog(self):
        """Assert the whole file is free of hard-coded Persian but in I18N.

        This is the actual deliverable of step 2-p: 48 JS-generated strings
        were Persian literals. A new one would silently be English-only.
        """
        js = self._script()
        start, end = self._catalog_span(js)
        persian = re.compile(r"[\u0600-\u06FF]")
        offenders = [
            (i + 1, line.strip())
            for i, line in enumerate(js.split("\n"))
            if persian.search(line) and not (start <= i <= end)
        ]
        self.assertEqual(
            offenders, [], f"Persian outside the catalog: {offenders[:5]}"
        )

    def test_every_t_key_exists_in_both_catalogs(self):
        """Assert t() is never called with an unknown key.

        t() falls back to the key name itself, so a typo would show up in the
        UI as raw dotted identifiers rather than as a failing test.
        """
        js = self._script()
        start, end = self._catalog_span(js)
        code = "\n".join(js.split("\n")[:start] + js.split("\n")[end + 1:])
        # (?<![A-Za-z0-9_$.]) keeps createElement("div") and join(", ")
        # out: both end in `t("` and would otherwise look like real keys.
        used = set(re.findall(r'(?<![A-Za-z0-9_$.])t\("([^"]+)"\)', code))
        self.assertGreater(len(used), 30, "t() barely used - hooks are stale")
        for lang in ("en", "fa"):
            missing = sorted(used - set(_catalog(self.html, lang)))
            self.assertEqual(
                missing, [], f"t() keys missing from {lang} catalog: {missing}"
            )

    def test_every_catalog_key_is_reachable(self):
        """Assert no dead key: each one is a hook or a t() call.

        Guards against a key that was superseded but left behind, which is
        what a dead `conn.error` looked like after 2-p.
        """
        js = self._script()
        start, end = self._catalog_span(js)
        code = "\n".join(js.split("\n")[:start] + js.split("\n")[end + 1:])
        used = set(re.findall(r'(?<![A-Za-z0-9_$.])t\("([^"]+)"\)', code))
        hooked = set(re.findall(r"data-i18n(?:-attr)?=\"(?:[^\"]*:)?([^\"]+)\"", self.html))
        keys = set(_catalog(self.html, "en"))
        dead = sorted(keys - used - hooked)
        self.assertEqual(dead, [], f"catalog keys nothing reads: {dead}")
        self.assertEqual(
            sorted(hooked - keys), [], f"hooks with no catalog key: {sorted(hooked - keys)}"
        )

    def test_language_switch_rerenders_runtime_panels(self):
        """Assert setLang re-renders the JS-built panels, not only the hooks.

        applyI18n() only reaches [data-i18n]. The status, missions, jobs,
        approvals and feed panels are written with innerHTML, so without a
        re-render they keep the previous language and the page is half
        translated. The re-render must wait for data to avoid a boot request.
        """
        m = re.search(
            r"function\s+setLang\s*\([^)]*\)\s*\{(.*?)\n  \}", self.html, re.DOTALL
        )
        self.assertIsNotNone(m, "setLang not found")
        body = m.group(1)
        self.assertIn("applyI18n()", body, "setLang must apply the static hooks")
        self.assertIn("DATA_ON_SCREEN", body, "setLang must gate the re-render")
        self.assertIn(
            "refresh()", body, "setLang must re-render the runtime panels"
        )
        self.assertLess(
            body.index("DATA_ON_SCREEN"),
            body.index("refresh()"),
            "the re-render must be gated on DATA_ON_SCREEN",
        )
        self.assertRegex(
            self.html,
            r"DATA_ON_SCREEN\s*=\s*true",
            "DATA_ON_SCREEN is never set, so a language switch would never "
            "re-render anything",
        )

    def test_timestamps_follow_the_chosen_language(self):
        """Assert the event feed stops hard-coding the fa-IR locale."""
        self.assertNotIn(
            'toLocaleTimeString("fa-IR")',
            self.html,
            "event timestamps are pinned to fa-IR and ignore the language",
        )
        self.assertIn(
            "toLocaleTimeString(localeFor())",
            self.html,
            "event timestamps must use the active locale",
        )


    # -- step 2-t: English default, selector, persistence, keyboard -----

    def test_product_default_is_english(self):
        """Assert DEFAULT_LANG is "en".

        Persian is the selectable side, not the default; the roadmap states
        this twice and 2-a left a TODO comment in place of the change.
        """
        m = re.search(r"""const\s+DEFAULT_LANG\s*=\s*["']([a-z]{2})["']""", self.html)
        self.assertIsNotNone(m, "DEFAULT_LANG not declared")
        self.assertEqual(
            m.group(1), "en", "product default must be English, Persian is optional"
        )

    def test_no_duplicate_key_in_either_catalog(self):
        """Assert each language block defines every key exactly once.

        dict() silently keeps the last duplicate, so this must be counted on
        the raw text, not on the parsed mapping.
        """
        for lang in ("en", "fa"):
            block = re.search(
                r"\n  " + lang + r":\s*\{(.*?)\n  \},", self.html, re.DOTALL
            )
            self.assertIsNotNone(block, f"no {lang} block")
            keys = re.findall(r'"([^"]+)":\s*"', block.group(1))
            dupes = sorted({k for k in keys if keys.count(k) > 1})
            self.assertEqual(dupes, [], f"duplicate keys in {lang}: {dupes}")

    def test_translation_key_fallback_chain(self):
        """Assert t() falls back current -> default -> the key itself.

        A missing key must never render as `undefined` or as empty text: the
        last resort is the key name, which is still identifiable in the UI.
        """
        m = re.search(r"function\s+t\(\s*key\s*\)\s*\{(.*?)\n\}", self.html, re.DOTALL)
        self.assertIsNotNone(m, "t() not found")
        body = m.group(1)
        self.assertIn("I18N[LANG]", body, "t() must try the active language first")
        self.assertIn(
            "I18N[DEFAULT_LANG]", body, "t() must fall back to the default language"
        )
        self.assertRegex(body, r"return\s+key;", "t() must fall back to the key name")
        # and the first two must be guarded, so a prototype key cannot leak
        self.assertIn(
            "hasOwnProperty", body, "t() lookups must be own-property guarded"
        )

    def test_every_key_resolves_in_both_languages(self):
        """Assert no key renders as itself - i.e. nothing is left untranslated."""
        for lang in ("en", "fa"):
            table = _catalog(self.html, lang)
            for key, value in table.items():
                self.assertNotEqual(
                    value.strip(), key, f"{lang}:{key} has no translation"
                )

    def test_language_selector_exists_and_is_labelled(self):
        """Assert a real <select> with both languages and an associated label."""
        self.assertRegex(
            self.html,
            r'<label[^>]*for="lang-select"',
            "the selector needs a <label for>, or a screen reader announces nothing",
        )
        self.assertRegex(self.html, r'<select[^>]*id="lang-select"', "no <select>")
        for value in ("en", "fa"):
            self.assertRegex(
                self.html,
                r'<option\s+value="' + value + r'"',
                f"the selector is missing the {value} option",
            )
        self.assertRegex(
            self.html,
            r"""\$?\(["']lang-select["']\)\.addEventListener\(\s*["']change["']""",
            "the selector has no change listener",
        )
        self.assertIn(
            "setLang(e.target.value)", self.html, "changing the selector must call setLang"
        )

    def test_selector_cannot_disagree_with_lang(self):
        """Assert setLang pushes LANG back into the selector.

        Without this the control keeps showing the old choice after boot has
        read a different language out of localStorage.
        """
        m = re.search(r"function\s+setLang\s*\([^)]*\)\s*\{(.*?)\n\}", self.html, re.DOTALL)
        self.assertIsNotNone(m, "setLang not found")
        self.assertIn(
            "syncLangSelect()", m.group(1), "setLang must sync the selector"
        )
        self.assertRegex(
            self.html, r"function\s+syncLangSelect\s*\(", "syncLangSelect is not defined"
        )

    def test_language_choice_is_persisted_and_validated(self):
        """Assert the choice survives a restart, and a corrupt one cannot break boot."""
        self.assertRegex(
            self.html, r'const\s+LANG_STORE_KEY\s*=\s*"[^"]+"', "no storage key constant"
        )
        self.assertRegex(self.html, r"function\s+loadLang\s*\(", "loadLang missing")
        self.assertRegex(self.html, r"function\s+persistLang\s*\(", "persistLang missing")
        m = re.search(r"function\s+loadLang\s*\(\s*\)\s*\{(.*?)\n\}", self.html, re.DOTALL)
        self.assertIsNotNone(m, "loadLang body not found")
        body = m.group(1)
        self.assertIn(
            "hasOwnProperty", body, "a hand-edited stored value must be validated"
        )
        self.assertIn("DEFAULT_LANG", body, "loadLang must fall back to the default")
        # The guard lives in the accessor, not in loadLang: a module-scope
        # read that throws takes the whole page down before it can render.
        for accessor in ("readStore", "writeStore"):
            m = re.search(
                r"function\s+" + accessor + r"\s*\([^)]*\)\s*\{(.*?)\n\}",
                self.html, re.DOTALL,
            )
            self.assertIsNotNone(m, f"{accessor} is missing")
            self.assertIn(
                "try {", m.group(1),
                f"{accessor} must catch, or a blocked-cookie profile cannot boot",
            )
        # stronger than asserting one function: no raw use may survive anywhere
        guarded = set()
        for accessor in ("readStore", "writeStore"):
            m = re.search(
                r"function\s+" + accessor + r"\s*\([^)]*\)\s*\{(.*?)\n\}",
                self.html, re.DOTALL,
            )
            for line in m.group(1).split("\n"):
                guarded.add(line.strip())
        raw = [
            line.strip()
            for line in self.html.split("\n")
            if "localStorage" in line
            and not line.strip().startswith("//")
            and line.strip() not in guarded
        ]
        self.assertEqual(
            raw, [], f"unguarded localStorage access: {raw}"
        )
        # one key name for both halves, so they cannot drift apart
        self.assertEqual(
            len(re.findall(r'["\']agent_os_lang["\']', self.html)),
            1,
            "the storage key is hard-coded somewhere instead of using LANG_STORE_KEY",
        )

    def test_clickable_rows_are_keyboard_reachable(self):
        """Assert no clickable row is a <div>.

        A div with onclick cannot be focused, cannot be activated with Enter
        or Space, and is not announced as a control. The mission and job rows
        are the only clickable ones; the approval row is a container whose
        actions are its own buttons, and must stay a div (a button inside a
        button is invalid).
        """
        for name in ("m", "j"):
            m = re.search(
                r'const\s+\w+\s*=\s*document\.createElement\(\s*"(\w+)"\s*\);\s*\n'
                r'\s*\w+\.type\s*=\s*"button";\s*\n'
                r'\s*\w+\.className\s*=\s*"item";\s*\n'
                # (?:escapeHtml\()? - the title may be escaped, and that is
                # the point. What this test cares about is the element type,
                # not which interpolation happens to come first.
                r'\s*\w+\.innerHTML\s*=\s*`<[^`]*\$\{(?:escapeHtml\()?' + name + r"\.",
                self.html,
            )
            self.assertIsNotNone(
                m, f"the {name} row is not built as a <button type=button>"
            )
        self.assertNotRegex(
            self.html,
            r'createElement\("div"\);\s*\n\s*\w+\.className\s*=\s*"item";[^;]*;\s*\n'
            r'\s*\w+\.innerHTML[^;]*;\s*\n\s*\w+\.onclick',
            "a clickable .item row is still a div",
        )
        self.assertIn(
            ":focus-visible", self.html, "a keyboard user must be able to see focus"
        )

    def test_every_user_supplied_interpolation_is_escaped(self):
        """A string scan, because the behavioural test below needs this to be
        true for the RIGHT reasons and this catches the next one that drifts.

        The exceptions are deliberate and each is either a number, built from
        the catalogue, or already-escaped markup. Anything else reaching
        innerHTML is a finding.
        """
        import re as _re
        allowed = ("escapeHtml(", "t(", "badge(", "escapeAttr(")
        offenders = []
        for m in _re.finditer(r"\.innerHTML\s*=\s*`([^`]*)`", self.html, _re.S):
            for e in _re.finditer(r"\$\{([^}]*)\}", m.group(1)):
                expr = e.group(1).strip()
                if not expr:
                    continue
                if any(k in expr for k in allowed):
                    continue
                # numbers, and markup that is already escaped upstream
                if _re.fullmatch(r"[\w.\[\]]*(attempt_no|seq)\b[\w.\[\]]*", expr):
                    continue
                if expr in ("actions.join(\"\")", "evidenceHtml", "ts", "e.kind",
                            "badges ? `<div class=\"m\">${badges}</div>` : \"\""):
                    continue
                if expr == "a.id":
                    # server-generated approval id, and escapeHtml would NOT
                    # help inside onclick: entities are decoded before the JS
                    # runs. Fixing it properly means moving the binding off
                    # inline onclick, which is tracked, not silently done here.
                    continue
                offenders.append(expr)
        self.assertEqual(
            offenders, [],
            f"these reach innerHTML without escaping: {offenders}")

    def test_no_nested_buttons(self):
        """Assert the approval row stays a container, not a button.

        Its two actions are inner <button>s; wrapping them in a button would
        produce <button><button>, which is invalid and unactivatable.
        """
        self.assertRegex(
            self.html,
            r'<div class="row-inline"[^>]*>\s*\n\s*<button class="ok"',
            "the approval actions are no longer sibling buttons",
        )
        for m in re.finditer(r'<button class="item"', self.html):
            self.fail("a static .item button appeared; check for nesting")


if __name__ == "__main__":
    unittest.main()
