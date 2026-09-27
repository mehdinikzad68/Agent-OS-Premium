"""Path logic tests for agent_os.paths.

The module is pure lexical path logic with no filesystem access, so these
tests exercise it entirely in memory. It must:
- canonicalize POSIX paths: collapse repeated slashes, resolve "." and "..",
  strip trailing slashes, and reject non-absolute input,
- decide containment by path components, never by string prefix,
- gate registration on environment, absoluteness, traversal and scope, in
  that order, reporting its decision through the Check dataclass.

Standard library only.
"""

from __future__ import annotations

import unittest

from agent_os.paths import (
    REASON_NOT_ABSOLUTE, REASON_OK, REASON_OUTSIDE_SCOPE, REASON_TRAVERSAL,
    REASON_WINDOWS_UNSUPPORTED, canonicalize, check_project_root, is_within,
)


class CanonicalizeTest(unittest.TestCase):
    """Lexical normalisation of POSIX paths."""

    def test_collapses_separators_and_dots(self):
        """Assert "/a//b/./c/../d/" collapses to "/a/b/d"."""
        self.assertEqual(canonicalize("/a//b/./c/../d/"), "/a/b/d")

    def test_strips_trailing_slash(self):
        """Assert "/a/b/" loses its trailing slash."""
        self.assertEqual(canonicalize("/a/b/"), "/a/b")

    def test_double_slash_is_root_not_a_name(self):
        """Assert "//" is the root, not an empty leading component."""
        self.assertEqual(canonicalize("//"), "/")

    def test_double_slash_before_a_name(self):
        """Assert "//a" collapses to "/a"."""
        self.assertEqual(canonicalize("//a"), "/a")

    def test_relative_path_raises(self):
        """Assert a relative path raises ValueError."""
        with self.assertRaises(ValueError):
            canonicalize("a/b")

    def test_empty_path_raises(self):
        """Assert the empty string raises ValueError."""
        with self.assertRaises(ValueError):
            canonicalize("")


class IsWithinTest(unittest.TestCase):
    """Containment decided by components, not by string prefix."""

    def test_scope_contains_itself(self):
        """Assert the scope itself counts as within."""
        self.assertTrue(is_within("/a/b", "/a/b"))

    def test_child_is_within(self):
        """Assert a deeper path below the scope is within."""
        self.assertTrue(is_within("/a/b", "/a/b/c"))

    def test_shared_string_prefix_is_not_containment(self):
        """Assert "/a/bc" is not within "/a/b" despite the shared prefix."""
        self.assertFalse(is_within("/a/b", "/a/bc"))

    def test_parent_is_not_within(self):
        """Assert the scope does not contain its own parent."""
        self.assertFalse(is_within("/a/b", "/a"))

    def test_root_contains_everything(self):
        """Assert any absolute path is within "/"."""
        self.assertTrue(is_within("/", "/etc"))


class CheckProjectRootTest(unittest.TestCase):
    """Registration gate: environment, absoluteness, traversal, scope."""

    def test_valid_path_is_ok(self):
        """Assert an in-scope absolute path is accepted."""
        result = check_project_root("/w/p", "/w", "wsl")
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, REASON_OK)
        self.assertEqual(result.canonical, "/w/p")

    def test_windows_environment_is_unsupported(self):
        """Assert environment "windows" is rejected."""
        result = check_project_root("/w/p", "/w", "windows")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, REASON_WINDOWS_UNSUPPORTED)

    def test_empty_environment_is_unsupported(self):
        """Assert an empty environment string is rejected as unsupported."""
        result = check_project_root("/w/p", "/w", "")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, REASON_WINDOWS_UNSUPPORTED)

    def test_relative_path_is_not_absolute(self):
        """Assert a relative raw path is rejected before any canonical work."""
        result = check_project_root("w/p", "/w", "wsl")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, REASON_NOT_ABSOLUTE)

    def test_traversal_into_scope_is_still_rejected(self):
        """Assert "/a/../b" is rejected even though canonical "/b" would be in scope."""
        result = check_project_root("/a/../b", "/a", "wsl")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, REASON_TRAVERSAL)

    def test_traversal_out_of_scope(self):
        """Assert "/a/../../etc" is rejected as traversal."""
        result = check_project_root("/a/../../etc", "/a", "wsl")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, REASON_TRAVERSAL)

    def test_path_outside_scope(self):
        """Assert "/etc" is outside scope "/w"."""
        result = check_project_root("/etc", "/w", "wsl")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, REASON_OUTSIDE_SCOPE)

    def test_sibling_prefix_is_outside_scope(self):
        """Assert "/wx" shares the string prefix of "/w" but is outside it."""
        result = check_project_root("/wx", "/w", "wsl")
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, REASON_OUTSIDE_SCOPE)

    def test_canonical_is_reported_on_failure(self):
        """Assert the canonical field is populated even when the check fails."""
        result = check_project_root("/etc", "/w", "wsl")
        self.assertFalse(result.ok)
        self.assertEqual(result.canonical, "/etc")

    def test_canonical_form_is_reported(self):
        """Assert "/w//p/./" reports canonical "/w/p"."""
        result = check_project_root("/w//p/./", "/w", "wsl")
        self.assertTrue(result.ok)
        self.assertEqual(result.canonical, "/w/p")


if __name__ == "__main__":
    unittest.main()
