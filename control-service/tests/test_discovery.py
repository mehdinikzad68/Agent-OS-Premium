"""Tests for tool discovery.

The claims worth defending, in order of how badly a bug would hurt:

1. A version is never invented. Every shape that cannot be parsed must yield
   confidence=unknown with version=None - not a guess, not a fallback regex
   that happens to find a number somewhere in the output.
2. Nothing outside the allowlist is ever executed. A test that only checks the
   happy path would not notice an allowlist that had quietly stopped working.
3. Discovery installs and writes nothing.
4. A tool on the allowlist that hangs is bounded, and discovery survives it.
5. An unsupported environment is refused rather than reported as empty.

Every test that needs a fake binary writes it into a temp dir and prepends that
dir to PATH, so the real PATH is never relied on and no real tool is executed
to make a test pass.
"""
import os
import pathlib
import stat
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from agent_os import discovery as D  # noqa: E402


def _make_tool(directory, name, body):
    """Write an executable stand-in and return its path."""
    p = pathlib.Path(directory) / name
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(p)


class AllowlistIsTheBoundary(unittest.TestCase):
    def test_a_name_outside_the_allowlist_is_never_executed(self):
        """The whole safety argument. If this breaks, discovery runs anything."""
        with tempfile.TemporaryDirectory() as d:
            marker = pathlib.Path(d) / "I-RAN"
            _make_tool(d, "eviltool", f"""\
                #!/bin/sh
                touch "{marker}"
                echo 'eviltool 6.6.6'
                """)
            with mock.patch.dict(os.environ, {"PATH": d}):
                tool = D.probe_tool("eviltool", "wsl")

        self.assertFalse(marker.exists(), "a non-allowlisted binary was executed")
        self.assertEqual(tool.confidence, D.CONFIDENCE_NOT_PROBED)
        self.assertIsNone(tool.version)

    def test_a_non_allowlisted_binary_is_still_reported_with_its_path(self):
        """Refusing to run it must not mean hiding it."""
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "othertool", "#!/bin/sh\necho hi\n")
            with mock.patch.dict(os.environ, {"PATH": d}):
                tool = D.probe_tool("othertool", "wsl")

        self.assertEqual(tool.confidence, D.CONFIDENCE_NOT_PROBED)
        self.assertIsNotNone(tool.path, "the candidate was hidden instead of refused")
        self.assertIn("allowlist", tool.note)

    def test_the_allowlist_is_not_empty_and_every_entry_is_well_formed(self):
        self.assertTrue(D.ALLOWED_PROBES, "an empty allowlist probes nothing")
        for name, spec in D.ALLOWED_PROBES.items():
            self.assertEqual(spec.name, name, f"{name}: spec/name disagree")
            self.assertTrue(spec.flags, f"{name}: no version flag")
            self.assertTrue(spec.version_pattern, f"{name}: no version pattern")


class VersionIsNeverInvented(unittest.TestCase):
    """Every shape that must produce unknown rather than a plausible number."""

    def _probe_with_output(self, body):
        with tempfile.TemporaryDirectory() as d:
            # name it 'faketool' and allowlist it for this test only
            _make_tool(d, "faketool", body)
            spec = D.ProbeSpec("faketool")  # default: the tool's own name
            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    return D.probe_tool("faketool", "wsl")

    def test_no_output_at_all(self):
        t = self._probe_with_output("#!/bin/sh\nexit 0\n")
        self.assertIsNone(t.version)
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)

    def test_unrelated_text_with_a_number_in_it(self):
        """The trap: 'loaded 3 plugins' must not become version 3."""
        t = self._probe_with_output(
            "#!/bin/sh\necho 'loaded 3 plugins and 2 daemons'\n")
        self.assertIsNone(t.version, "a number was scraped out of unrelated text")
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)

    def test_nonzero_exit_is_not_a_version(self):
        t = self._probe_with_output("#!/bin/sh\necho 'faketool 1.0'\nexit 3\n")
        self.assertIsNone(t.version)
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)

    def test_error_text_on_stderr(self):
        t = self._probe_with_output(
            "#!/bin/sh\necho 'error: unknown option --version' 1>&2\nexit 1\n")
        self.assertIsNone(t.version)
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)

    def test_a_version_buried_mid_line_is_not_read(self):
        """A version must lead the line, not appear somewhere inside it.

        This is the case that a search() instead of match() would pass.
        """
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "faketool", """\
                #!/bin/sh
                echo 'faketool build host alpha 7 loaded 3 plugins'
                """)
            spec = D.ProbeSpec("faketool")
            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    t = D.probe_tool("faketool", "wsl")
        self.assertIsNone(t.version, "a number was taken from mid-line text")
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)

    def test_a_dotted_number_inside_prose_is_not_a_version(self):
        """Guards the TOKEN itself, not just the anchor.

        "module 1.2.3-alpha loaded" must not yield "1.2.3-alpha".
        """
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "faketool", """\
                #!/bin/sh
                echo 'using plugin version 1.2.3-alpha today'
                """)
            spec = D.ProbeSpec("faketool")
            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    t = D.probe_tool("faketool", "wsl")
        self.assertIsNone(t.version)

    def test_a_banner_line_does_not_hide_a_later_version_line(self):
        """Only the FIRST non-empty line is the answer.

        A later line that looks exactly like a valid version must not be
        harvested when the first line was a banner. Reading further is how a
        system starts reporting a version it invented from an unrelated line.
        """
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "faketool", """\
                #!/bin/sh
                echo 'starting up'
                echo 'faketool 9.9.9'
                """)
            spec = D.ProbeSpec("faketool")
            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    t = D.probe_tool("faketool", "wsl")
        self.assertIsNone(t.version, "a later line was harvested")
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)
        self.assertTrue(t.path, "the tool is still reported as present")

    def test_an_empty_version_string_is_never_reported_as_a_version(self):
        """None and '' are different lies: '' looks like a known value."""
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "faketool", "#!/bin/sh\necho 'faketool'\n")
            spec = D.ProbeSpec("faketool")
            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    t = D.probe_tool("faketool", "wsl")
        self.assertIsNotNone(t.version is None or t.version != "",
                            "an empty string was reported as a version")
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)

    def test_a_malformed_version_token_is_not_a_version(self):
        """Closes a real gap found by mutation.

        Relaxing the version token to any run of digits and dots changed no
        test outcome, because nothing fed it a malformed token. These are the
        strings a loose pattern would happily accept.
        """
        spec = D.ProbeSpec("faketool")
        for line, why in (
            ("faketool 1..0", "an empty component"),
            ("faketool ...", "dots with no digits"),
            ("faketool 1.2.3-alpha", "valid, and must still be accepted"),
            ("faketool v2.0", "a v prefix is accepted and stripped"),
        ):
            got = D._read_version(line, spec)
            if why.startswith("valid"):
                self.assertEqual(got, "1.2.3-alpha", why)
            elif why.startswith("a v prefix"):
                # the printed form is "v2.0"; the stored form drops the prefix
                self.assertEqual(got, "2.0", why)
            else:
                self.assertIsNone(got, f"{why}: {line!r} -> {got!r}")

    def test_read_version_itself_never_returns_an_empty_string(self):
        """Directly on the helper, so no probe path can smuggle one through."""
        spec = D.ProbeSpec("faketool")
        for line in ("", "   ", "faketool", "faketool ", "faketool v"):
            got = D._read_version(line, spec)
            self.assertFalse(got == "", f"{line!r} produced an empty version")

    def test_a_version_on_a_later_line_is_not_harvested(self):
        """Only the first meaningful line counts.

        Otherwise a banner mentioning an unrelated number becomes the version.
        """
        t = self._probe_with_output(
            "#!/bin/sh\necho 'starting up'\necho 'faketool 9.9.9'\n")
        self.assertIsNone(t.version)

    def test_version_is_none_not_an_empty_string(self):
        """An empty version is a lie of a different kind: it looks known."""
        t = self._probe_with_output("#!/bin/sh\necho 'faketool 1.0'\n")
        t2 = self._probe_with_output("#!/bin/sh\nexit 0\n")
        self.assertIsNotNone(t.version)
        self.assertIsNone(t2.version)

    def test_an_unknown_version_still_reports_that_the_tool_exists(self):
        t = self._probe_with_output("#!/bin/sh\nexit 0\n")
        self.assertIsNotNone(t.path, "an unreadable version must not lose the tool")


class DiscoveryIsReadOnly(unittest.TestCase):
    def test_discovery_writes_nothing_into_the_working_directory(self):
        """A probe is read-only in the sense that matters: it creates no state."""
        with tempfile.TemporaryDirectory() as d:
            tool_dir = pathlib.Path(d) / "bin"
            tool_dir.mkdir()
            _make_tool(str(tool_dir), "faketool", "#!/bin/sh\necho 'faketool 1.0'\n")
            work = pathlib.Path(d) / "work"
            work.mkdir()
            spec = D.ProbeSpec("faketool")  # default: the tool's own name

            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": str(tool_dir)}):
                    with mock.patch.object(D, "_run") as m:
                        m.return_value = (0, "faketool 1.0", "")
                        D.probe_tool("faketool", "wsl")

            self.assertEqual(
                list(work.iterdir()), [],
                "discovery created files in the working directory")
            self.assertEqual(
                sorted(p.name for p in tool_dir.iterdir()), ["faketool"],
                "discovery added or removed files")

    def test_a_probe_that_writes_a_file_is_visible_as_a_real_hazard(self):
        """Documents WHY the allowlist is the boundary, rather than asserting it.

        A binary that writes on --version does write. Discovery cannot prevent
        that; it can only choose not to run unknown binaries. If this test ever
        starts failing because a temp dir is not writable, the hazard claim
        itself needs revisiting.
        """
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "writertool", f"""\
                #!/bin/sh
                echo 'writertool 1.0'
                touch "{pathlib.Path(d) / 'side-effect'}"
                """)
            spec = D.ProbeSpec("writertool")
            # APPEND so `touch` resolves; replacing PATH made the script exit
            # 127 before writing, which would have quietly voided the claim.
            path_with_d = d + os.pathsep + os.environ.get("PATH", "")
            with mock.patch.dict(D.ALLOWED_PROBES, {"writertool": spec}):
                with mock.patch.dict(os.environ, {"PATH": path_with_d}):
                    D.probe_tool("writertool", "wsl")
            self.assertTrue(
                (pathlib.Path(d) / "side-effect").exists(),
                "the hazard is real: a probed binary wrote a file")


class ProbesAreBounded(unittest.TestCase):
    def test_a_hanging_probe_is_cut_off_and_survived(self):
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "hangtool", "#!/bin/sh\nsleep 30\n")
            spec = D.ProbeSpec("hangtool")
            # APPEND, never replace: the script calls `sleep`, so /bin has to
            # stay on PATH for it to hang at all. Replacing PATH made it exit
            # 127 immediately and the timeout was never exercised.
            path_with_d = d + os.pathsep + os.environ.get("PATH", "")
            with mock.patch.dict(D.ALLOWED_PROBES, {"hangtool": spec}):
                with mock.patch.dict(os.environ, {"PATH": path_with_d}):
                    with mock.patch.object(D, "PROBE_TIMEOUT_SECONDS", 0.4):
                        t = D.probe_tool("hangtool", "wsl")
        self.assertIsNone(t.version)
        self.assertEqual(t.confidence, D.CONFIDENCE_UNKNOWN)
        self.assertIn("timed out", t.note)

    def test_one_bad_candidate_does_not_abort_the_whole_run(self):
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "goodtool", "#!/bin/sh\necho 'goodtool 2.0'\n")
            specs = {"goodtool": D.ProbeSpec("goodtool"),
                     "brokentool": D.ProbeSpec("brokentool")}
            with mock.patch.dict(D.ALLOWED_PROBES, specs):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    r = D.discover(["brokentool", "goodtool"], "wsl")
        names = {t.name: t for t in r.tools}
        self.assertIn("goodtool", names)
        self.assertEqual(names["goodtool"].version, "2.0")

    def test_a_missing_binary_is_not_an_error(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent-dir"}):
            t = D.probe_tool("python3", "wsl")
        self.assertIsNone(t.path)
        self.assertEqual(t.confidence, D.CONFIDENCE_NOT_PROBED)
        self.assertIn("not found", t.note)


class EnvironmentIsHonest(unittest.TestCase):
    def test_an_unsupported_environment_is_refused_not_reported_empty(self):
        """An empty list would read as 'nothing is installed'. It is a refusal."""
        with self.assertRaises(D.EnvironmentUnsupported):
            D.discover(["python3"], "windows")
        with self.assertRaises(D.EnvironmentUnsupported):
            D.search_path("windows")

    def test_supported_environments_match_what_is_verified(self):
        self.assertEqual(D.SUPPORTED_ENVIRONMENTS, ("wsl",))

    def test_a_windows_mount_binary_is_labelled_not_refused(self):
        """A WSL shim genuinely runs. Refusing it would discard a working tool.

        This is the case that inverted the first design guess.
        """
        with tempfile.TemporaryDirectory() as d:
            fake_mount = pathlib.Path(d) / "mnt" / "c" / "tools"
            fake_mount.mkdir(parents=True)
            _make_tool(str(fake_mount), "shtool", "#!/bin/sh\necho 'shtool 4.5'\n")
            spec = D.ProbeSpec("shtool")
            with mock.patch.object(D, "_provenance",
                                   return_value="windows_mount"):
                with mock.patch.dict(D.ALLOWED_PROBES, {"shtool": spec}):
                    with mock.patch.dict(os.environ, {"PATH": str(fake_mount)}):
                        t = D.probe_tool("shtool", "wsl")
        self.assertEqual(t.confidence, D.CONFIDENCE_EXACT)
        self.assertEqual(t.version, "4.5")
        self.assertEqual(t.provenance, "windows_mount")
        self.assertIn("Windows install", t.note)

    def test_provenance_detection_is_about_the_path_not_the_tool(self):
        self.assertEqual(D._provenance("/usr/bin/git"), "posix")
        self.assertEqual(D._provenance("/home/mehdi/.local/bin/agy"), "posix")
        self.assertEqual(D._provenance("/mnt/c/Users/x/node/dsh"), "windows_mount")
        # a directory that merely starts with /mnt is not a drive mount
        self.assertEqual(D._provenance("/mnt/data/tools/x"), "posix")


class ResultShape(unittest.TestCase):
    def test_skipped_candidates_are_reported_not_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "unlisted", "#!/bin/sh\necho 'unlisted 1.0'\n")
            with mock.patch.dict(os.environ, {"PATH": d}):
                r = D.discover(["unlisted"], "wsl")
        self.assertEqual(r.tools, [])
        self.assertEqual(len(r.skipped), 1)
        self.assertEqual(r.skipped[0].name, "unlisted")

    def test_a_name_absent_everywhere_is_not_listed_at_all(self):
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent-dir"}):
            r = D.discover(["definitely-not-here"], "wsl")
        self.assertEqual(r.tools, [])
        self.assertEqual(r.skipped, [])

    def test_duplicate_names_are_probed_once(self):
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "faketool", "#!/bin/sh\necho 'faketool 1.0'\n")
            spec = D.ProbeSpec("faketool")  # default: the tool's own name
            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    with mock.patch.object(D, "_run",
                                           return_value=(0, "faketool 1.0", "")) as m:
                        r = D.discover(["faketool", "faketool", " faketool "],
                                       "wsl")
        self.assertEqual(len(r.tools), 1)
        self.assertEqual(m.call_count, 1)

    def test_the_result_serialises_without_hidden_fields(self):
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "faketool", "#!/bin/sh\necho 'faketool 1.0'\n")
            spec = D.ProbeSpec("faketool")  # default: the tool's own name
            with mock.patch.dict(D.ALLOWED_PROBES, {"faketool": spec}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    with mock.patch.object(D, "_run",
                                           return_value=(0, "faketool 1.0", "")):
                        r = D.discover(["faketool"], "wsl")
        payload = r.to_dict()
        self.assertEqual(payload["environment"], "wsl")
        self.assertIn("skipped", payload)
        entry = payload["tools"][0]
        for key in ("name", "environment", "path", "version", "confidence",
                    "note", "provenance"):
            self.assertIn(key, entry)


class SearchPath(unittest.TestCase):
    def test_search_lists_only_allowlisted_names(self):
        with tempfile.TemporaryDirectory() as d:
            _make_tool(d, "listed", "#!/bin/sh\ntrue\n")
            (pathlib.Path(d) / "randomfile").write_text("x", encoding="utf-8")
            with mock.patch.dict(D.ALLOWED_PROBES,
                                 {"listed": D.ProbeSpec("listed")}):
                with mock.patch.dict(os.environ, {"PATH": d}):
                    self.assertEqual(D.search_path("wsl"), ["listed"])

    def test_an_unreadable_path_entry_is_skipped_not_fatal(self):
        with mock.patch.dict(os.environ,
                             {"PATH": "/nonexistent-a" + os.pathsep + "/nonexistent-b"}):
            self.assertEqual(D.search_path("wsl"), [])


if __name__ == "__main__":
    unittest.main()
