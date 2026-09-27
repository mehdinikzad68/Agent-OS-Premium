# -*- coding: utf-8 -*-
"""The command field is validated at the API edge, and the approval bypass is
declared out loud. Both facts are load-bearing, so both are pinned here.

Written after the independent review, which found that `command` reached Popen
with whatever JSON type the caller sent. Proven at the time: a string raises
FileNotFoundError, an int or dict raises TypeError, and both surfaced as a 500
for what is plainly a bad request raised by the wrong layer.

The known 500 on a *valid* argv list is a separate defect (F8: the column is
TEXT and sqlite cannot bind a list) with a separate fix. Nothing here depends
on it, and no test was written around it - a test that pins a known break
either fails forever or gets deleted, and both outcomes lose the information.
"""
import pathlib
import unittest

from agent_os.api import AgentOSApi, ApiError


class _Unbound:
    """_require_command reads no instance state, so no construction is needed.

    Deliberately not a real AgentOSApi: building one would need a store, a db
    and a token, and the method under test touches none of it. Calling the
    unbound function with None for self keeps the test about the validation
    rather than about fixtures.

    Note it has to be a wrapper, not `require_command = AgentOSApi._require_command`.
    Assigned as a class attribute it becomes a method again, so `self.v(x)`
    would pass x as self and the call would fail with "missing 1 required
    positional argument" - which is exactly what it did the first time.
    """

    @staticmethod
    def require_command(value):
        return AgentOSApi._require_command(None, value)


class CommandValidationTest(unittest.TestCase):
    def setUp(self):
        self.v = _Unbound.require_command

    def test_absent_is_allowed_and_means_fail_closed_later(self):
        # The executor refuses an empty command itself, with a message asking
        # the caller to set one. Validating here must not second-guess that.
        self.assertIsNone(self.v(None))

    def test_a_proper_argv_list_is_accepted(self):
        self.assertEqual(self.v(["python", "-c", "print(1)"]),
                         ["python", "-c", "print(1)"])

    def test_the_good_value_is_copied_not_aliased(self):
        # A caller mutating its list afterwards must not be able to change what
        # was already validated and handed on.
        src = ["echo", "hi"]
        out = self.v(src)
        src.append("injected")
        self.assertEqual(out, ["echo", "hi"])

    def test_a_bare_string_is_refused(self):
        # Proven against Popen: a string becomes argv[0] literally and raises
        # FileNotFoundError, so it cannot be the shape that works.
        with self.assertRaises(ApiError) as c:
            self.v("echo hi")
        self.assertEqual(c.exception.status, 400)
        self.assertEqual(c.exception.code, "command_not_a_list")

    def test_wrong_container_types_are_refused(self):
        for bad in (42, 3.5, {"a": 1}, (), "echo", True, frozenset()):
            with self.subTest(bad=repr(bad)):
                with self.assertRaises(ApiError) as c:
                    self.v(bad)
                self.assertEqual(c.exception.code, "command_not_a_list")

    def test_an_empty_list_is_refused(self):
        # [] and None both read as "no command" to the executor, so allowing
        # [] would give one refusal two spellings.
        with self.assertRaises(ApiError):
            self.v([])

    def test_a_bad_element_names_its_index(self):
        with self.assertRaises(ApiError) as c:
            self.v(["echo", 7])
        self.assertIn("command[1]", c.exception.message)
        with self.assertRaises(ApiError) as c:
            self.v(["echo", ""])
        self.assertIn("command[1]", c.exception.message)

    def test_whitespace_only_elements_are_refused(self):
        with self.assertRaises(ApiError):
            self.v(["echo", "   "])

    def test_the_message_does_not_echo_the_payload(self):
        # The message goes back to the browser. It should name the type it got,
        # not hand the caller its own input back.
        with self.assertRaises(ApiError) as c:
            self.v({"secret": "value"})
        self.assertNotIn("value", c.exception.message)
        self.assertIn("dict", c.exception.message)


class BypassIsDeclaredTest(unittest.TestCase):
    """The roadmap's Phase 5 exit criterion: the bypass path must be identified
    or explicitly declared. This pins the declaration, because deleting it
    breaks nothing else - the module still starts and every other test passes.
    """

    @classmethod
    def setUpClass(cls):
        cls.text = (pathlib.Path(__file__).resolve().parents[1]
                    / "agent_os" / "cli.py").read_text(encoding="utf-8")

    def test_the_banner_states_there_is_no_approval_gate(self):
        self.assertIn("NO approval gate", self.text)

    def test_the_banner_names_the_phase_that_will_build_it(self):
        self.assertIn("Phase 5", self.text)

    def test_the_banner_does_not_claim_the_working_copy_is_a_boundary(self):
        # The phrase must survive as a negation. If someone later rewrote this
        # into a reassurance, this fails - which is the point.
        self.assertIn("not a security boundary", self.text)

    def test_the_bypass_is_also_a_structured_event_not_only_a_print(self):
        # A print dies with the terminal; the event is queryable later.
        self.assertIn("executor.bypass_declared", self.text)
        self.assertIn("approval_gate=False", self.text)

    def test_the_event_is_logged_at_WARNING_not_INFO(self):
        # Added after mutation M5 survived twice. The first attempt looked 200
        # characters back from the event name for logging.WARNING and still
        # missed, because the warning TEXT is ~500 characters long and the
        # window landed inside that string. Anchor on the log_event( call
        # itself and read the segment between it and the event name.
        i = self.text.find('"executor.bypass_declared"')
        self.assertGreater(i, 0, "the event name is gone entirely")
        j = self.text.rfind("log_event(", 0, i)
        self.assertGreater(j, 0, "the event is no longer emitted by log_event()")
        self.assertIn("logging.WARNING", self.text[j:i],
                      "the bypass event must be logged at WARNING, not INFO")

    def test_all_four_risk_facts_are_in_the_single_event(self):
        # One event, four fields, so an operator reading the event store sees
        # the whole picture in one record instead of correlating three lines.
        i = self.text.find('"executor.bypass_declared"')
        window = self.text[i:i + 500]
        for field in ("approval_gate=False", "approval_gate_planned_phase=",
                      "writes_bounded=False", "timeout_kills_process_group="):
            self.assertIn(field, window, f"{field} is missing from the event")

    def test_the_event_records_the_unbounded_writes_fact_too(self):
        # Declaring only the approval gap would understate the risk: the child
        # can write outside the sandbox, and a timeout kills only the direct
        # child. Both belong in the same declaration.
        self.assertIn("writes_bounded=False", self.text)
        self.assertIn("timeout_kills_process_group=False", self.text)


if __name__ == "__main__":
    unittest.main()
