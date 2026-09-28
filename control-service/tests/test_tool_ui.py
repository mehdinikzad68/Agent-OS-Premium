"""The Phase 3 tool panel, checked as structure rather than as pixels.

A browser cannot reach the WSL server from this host, so the panel is verified
the way this project has verified UI before: assert on the served HTML and on
the handlers, not on a screenshot.

The claims worth defending, in order of how badly a bug would hurt:

1. Tool-supplied strings are escaped. `path`, `version` and `note` come from a
   binary's own output and from the filesystem, so they are untrusted. A tool
   named `<img onerror=...>` must never become markup. This is the F1 lesson:
   the project's UI scanner did not catch an unescaped variable, so the check
   here is on the value being passed, not on the surrounding text.

2. The page states that discovery grants no execution rights. If that sentence
   is removed, the panel starts implying a permission it does not have.

3. An `unknown` version is shown as unknown, never as a blank or a guess.

4. `provenance=windows_mount` is visible, so a Windows version is not read as a
   POSIX one.

5. Both operations exist: register and remove, wired to the right endpoints.

6. Discovery is a button press, not something that runs on every refresh. It
   executes binaries; a page that probed on a timer would be a surprise.
"""
import pathlib
import re
import unittest

D = pathlib.Path(__file__).resolve().parents[1]
HTML = (D / "agent_os" / "web" / "index.html").read_text(encoding="utf-8")


class ToolPanelMarkup(unittest.TestCase):
    def test_the_panel_exists_with_both_lists(self):
        # two separate lists on purpose: found vs registered are different facts
        self.assertIn('id="tool-discovery"', HTML)
        self.assertIn('id="tool-list"', HTML)

    def test_the_discover_button_exists(self):
        self.assertIn('id="tool-discover"', HTML)

    def test_the_safety_statement_is_on_the_page(self):
        """The claim the whole phase rests on, stated where a reader sees it."""
        self.assertIn('data-i18n="ui.toolsSafety"', HTML)
        for lang, needle in (("en", "NOT permitted to run"),
                             ("fa", "مجاز به اجرا نیست")):
            self.assertIn(needle, HTML,
                          f"the {lang} safety sentence is missing")

    def test_registry_rows_are_labelled_as_granting_nothing(self):
        # rendered at runtime through t(), not a data-i18n hook
        self.assertIn('t("ui.toolsNoExec")', HTML)
        for needle in ("grants no execution", "بدون اجازهٔ اجرا"):
            self.assertIn(needle, HTML,
                          "a registered row is not labelled as inert")


class ToolPanelEscaping(unittest.TestCase):
    """The F1 lesson applied to a panel fed by untrusted data."""

    def _function_body(self, name: str) -> str:
        i = HTML.find(f"function {name}(")
        self.assertNotEqual(i, -1, f"{name} is not defined")
        # take up to the next top-level function
        j = HTML.find("\nfunction ", i + 1)
        return HTML[i:j if j != -1 else len(HTML)]

    def test_tool_supplied_values_are_escaped(self):
        body = self._function_body("renderDiscovery")
        for expr in ('escapeHtml(tool.path || "")',
                     'escapeHtml(tool.version || t("ui.toolsVersionUnknown"))',
                     'escapeHtml(tool.note || "")',
                     "escapeHtml(tool.name)"):
            self.assertIn(expr, body,
                          f"{expr!r} is missing: the value would reach "
                          f"innerHTML unescaped")

    def test_the_escaped_values_are_stored_in_named_variables(self):
        """The project's UI scanner accepts a variable name only when it is
        recognisably the escaped one (F1 renamed its variable to cmdSafe for
        exactly this reason). So the intermediate names must say so."""
        body = self._function_body("renderDiscovery")
        for name in ("pathSafe", "verSafe", "noteSafe"):
            self.assertIn(name, body, f"{name} is missing")

    def test_registry_rows_escape_their_values_too(self):
        body = self._function_body("loadTools")
        for expr in ('escapeHtml(tool.path || "")',
                     'escapeHtml(tool.version || t("ui.toolsVersionUnknown"))',
                     "escapeHtml(tool.name)"):
            self.assertIn(expr, body,
                          f"{expr!r} is missing in the registry rows")

    def test_no_tool_field_is_interpolated_raw(self):
        """Catch the shape a reviewer would miss: `${tool.path}` directly."""
        body = self._function_body("renderDiscovery") + self._function_body("loadTools")
        for bad in ("${tool.path}", "${tool.version}", "${tool.note}",
                    "${tool.name}"):
            self.assertNotIn(bad, body,
                             f"{bad} is interpolated without escapeHtml")

    def test_the_skipped_list_uses_text_content_not_html(self):
        body = self._function_body("renderDiscovery")
        # names come from a directory listing, so they are untrusted too
        self.assertIn("wrap.textContent", body,
                      "the skipped list should be built with textContent")


class ToolPanelHonesty(unittest.TestCase):
    def test_an_unknown_version_has_a_visible_label(self):
        self.assertIn("ui.toolsVersionUnknown", HTML)
        self.assertIn("_toolConfidenceBadgeHtml", HTML)

    def test_the_badge_covers_the_unknown_case(self):
        body = HTML[HTML.find("function _toolConfidenceBadgeHtml("):][:600]
        self.assertIn('confidence === "unknown"', body,
                      "an unknown version is not given its own label")

    def test_windows_provenance_is_surfaced(self):
        self.assertIn("_toolProvenanceNoteHtml", HTML)
        self.assertIn("windows_mount", HTML)
        body = HTML[HTML.find("function _toolProvenanceNoteHtml("):][:500]
        self.assertIn('provenance !== "windows_mount"', body)

    def test_a_blank_version_is_never_rendered_as_blank(self):
        body = HTML[HTML.find("function renderDiscovery("):][:3000]
        self.assertIn("tool.version || t(\"ui.toolsVersionUnknown\")", body,
                      "a missing version would render as empty, which reads "
                      "as known-but-blank rather than unknown")


class ToolPanelWiring(unittest.TestCase):
    def test_registration_posts_to_the_registry(self):
        self.assertIn('api("POST", "/api/tools/registry"', HTML)

    def test_removal_deletes_by_id(self):
        self.assertIn('api("DELETE", "/api/tools/registry/" + tool.id)', HTML)

    def test_discovery_hits_the_discovery_endpoint(self):
        self.assertIn('api("GET", "/api/tools/discover"', HTML)

    def test_the_registry_loads_on_refresh(self):
        i = HTML.find("async function refresh()")
        body = HTML[i:i + 700]
        self.assertIn("loadTools()", body,
                      "the registry should load with the rest of the page")

    def test_discovery_does_not_run_on_every_refresh(self):
        """It executes binaries. A refresh must not silently probe."""
        i = HTML.find("async function refresh()")
        body = HTML[i:i + 700]
        self.assertNotIn("runDiscovery()", body,
                         "discovery runs on refresh; it must be a button press")

    def test_the_discover_button_is_wired(self):
        self.assertIn('$(\\"tool-discover\\")', HTML.replace('"', '\\"'))
        self.assertIn("$(\"tool-discover\").addEventListener", HTML)

    def test_a_failed_registration_surfaces_the_reason(self):
        body = HTML[HTML.find("function renderDiscovery("):][:3000]
        self.assertIn("reasonText", body,
                      "a refused registration must show why, not fail silently")

    def test_a_removed_row_refreshes_the_list(self):
        body = HTML[HTML.find("async function loadTools("):][:2500]
        self.assertIn("await loadTools()", body,
                      "the list must refresh after a removal")


class ToolPanelTranslations(unittest.TestCase):
    def test_every_new_key_exists_in_both_languages(self):
        keys = ["ui.tools", "ui.toolsSafety", "ui.toolsDiscover",
                "ui.toolsRegistry", "ui.toolsNone", "ui.toolsRegister",
                "ui.toolsRemove", "ui.toolsRegisterFail", "ui.toolsRemoveFail",
                "ui.toolsDiscoverFail", "ui.toolsVersionUnknown",
                "ui.toolsSkipped", "ui.toolsSkippedHint", "ui.toolsNoExec"]
        for k in keys:
            hits = len(re.findall(rf'"{re.escape(k)}"\s*:', HTML))
            self.assertEqual(hits, 2,
                             f"{k} is defined {hits} time(s); a key present in "
                             f"only one language renders as the raw key")

    def test_the_persian_safety_line_uses_zwnj(self):
        """Persian typography rule: compounds need U+200C, not a space."""
        m = re.search(r'"ui\.toolsSafety": "([^"]*)"', HTML)
        self.assertIsNotNone(m)
        persian_lines = [ln for ln in m.groups()]
        # the second definition is the fa table
        fa = None
        for g in re.findall(r'"ui\.toolsSafety": "([^"]*)"', HTML):
            if re.search(r"[\u0600-\u06FF]", g):
                fa = g
        self.assertIsNotNone(fa, "the Persian safety sentence is missing")
        # words that are compound nouns must be joined with ZWNJ
        for pair in ("فقط\u200cخواندنی", "می\u200cدهد", "کشف\u200cشده"):
            self.assertIn(pair, fa, f"expected ZWNJ form {pair!r} in the fa text")


class ToolPanelIsolation(unittest.TestCase):
    def test_discovery_and_registry_are_separate_elements(self):
        """A reader must be able to tell what was found from what was kept."""
        disc = HTML.find('id="tool-discovery"')
        reg = HTML.find('id="tool-list"')
        self.assertNotEqual(disc, -1)
        self.assertNotEqual(reg, -1)
        self.assertNotEqual(disc, reg)

    def test_the_panel_does_not_claim_a_tool_can_be_run(self):
        """No copy anywhere may say a registered tool is runnable."""
        for bad in ("run this tool", "اجرای ابزار", "execute tool",
                    "runTool", "executeTool"):
            self.assertNotIn(bad, HTML,
                             f"the panel claims an execution capability: {bad!r}")

    def test_no_executor_wiring_from_the_panel(self):
        """The panel must not be able to send a job to a discovered tool."""
        i = HTML.find("function renderDiscovery(")
        body = HTML[i:i + 4000]
        for bad in ("/api/jobs", "dispatch", "executor"):
            self.assertNotIn(bad, body,
                             f"the discovery panel references {bad!r}")


class ToolPanelCoexistsWithTheSecurityScan(unittest.TestCase):
    def test_the_repo_escaping_scanner_still_covers_this_panel(self):
        """The new panel must be judged by the EXISTING scanner, not only by
        the tests written alongside it.

        A panel that adds its own allowlist entries and is then checked only by
        its own tests can drift into a state the repo scan would reject. This
        runs that scan directly, so a weakened allowlist fails here too.
        """
        import importlib
        mod = importlib.import_module("tests.test_ui_i18n")
        mod.UiI18nTest.setUpClass()   # self.html is a CLASS attribute here
        inst = mod.UiI18nTest("test_every_user_supplied_interpolation_is_escaped")
        try:
            inst.test_every_user_supplied_interpolation_is_escaped()
        except AssertionError as e:
            self.fail(f"the repo escaping scanner rejects the page: {e}")

    def test_the_new_allowlist_entries_are_documented(self):
        """A bare allowlist entry is how a scanner quietly stops scanning.

        Each new name must sit next to a comment saying what makes it safe, so
        the next reader can question it instead of trusting it.
        """
        i = HTML.find("test_every_user_supplied_interpolation_is_escaped")
        self.assertNotEqual(i, -1, "the escaping test is gone from the page")
        src = (D / "tests" / "test_ui_i18n.py").read_text(encoding="utf-8")
        for name in ("verSafe", "pathSafe", "noteSafe"):
            self.assertIn(name, src, f"{name} is not in the scanner allowlist")
        j = src.find('"cmdSafe", "verSafe"')
        if j != -1:
            after = src[j:j + 1400]
            self.assertIn("escaped at construction", after,
                          "the new allowlist entries have no justification")

if __name__ == "__main__":
    unittest.main()
