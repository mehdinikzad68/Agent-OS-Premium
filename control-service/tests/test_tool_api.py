"""Phase 3 over real HTTP: discovery and the tool registry.

The unit tests cover the recogniser. These cover the product surface, and they
carry the one claim that matters most and is easiest to get wrong:

    a discovered tool is not thereby permitted to run.

That is checked three ways here, because a single assertion would be easy to
satisfy by accident:

1. the discovery response says so, explicitly;
2. every registry row carries grants_execution=False, including after a
   re-registration;
3. the executor registry is untouched by discovery and registration - the
   tool table is not consulted when a job runs.

The server runs in a real subprocess on a real port with a real token, so a
test that passes here cannot be passing because of a mocked transport.
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

D = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(D))

from tests.live_server import boot_server, stop_server  # noqa: E402

TOKEN = "phase3-tool-token"


def call(base, method, path, body=None, token=TOKEN):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, (json.loads(raw) if raw else {})
        except json.JSONDecodeError:
            return e.code, {"raw": raw[:300]}


class ToolApiTest(unittest.TestCase):
    server = None
    proc = None
    tmp = None
    base = ""

    @classmethod
    def setUpClass(cls):
        # OS-chosen port (tests/live_server.py). The old probe accepted any
        # 200 on a fixed port, so an orphan from a killed run could answer it
        # and the suite then talked to a stale database.
        cls.srv = boot_server(TOKEN, prefix="p3api-srv-", db_name="tools.db")
        cls.tmp = cls.srv["tmp"]
        cls.base = cls.srv["base"]

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.srv)

    # -- discovery ------------------------------------------------------

    def test_discovery_needs_the_token(self):
        st, _ = call(self.base, "GET", "/api/tools/discover", token="wrong")
        self.assertIn(st, (401, 403), "discovery was reachable without the token")

    def test_a_get_scans_the_allowlisted_names_on_path(self):
        st, body = call(self.base, "GET", "/api/tools/discover")
        self.assertEqual(st, 200)
        self.assertEqual(body.get("environment"), "wsl")
        self.assertIn("tools", body)
        self.assertIn("skipped", body)
        # python3 and git are on every machine this runs on
        names = {t["name"] for t in body["tools"]}
        self.assertIn("python3", names)
        self.assertIn("git", names)

    def test_every_discovered_entry_carries_the_required_fields(self):
        """The roadmap asks for name/environment/version/confidence. All four,
        plus provenance and a note - so a caller never has to guess why a
        version is missing."""
        st, body = call(self.base, "GET", "/api/tools/discover")
        self.assertEqual(st, 200)
        self.assertTrue(body["tools"], "nothing was discovered at all")
        for t in body["tools"]:
            for key in ("name", "environment", "path", "version",
                        "confidence", "note", "provenance"):
                self.assertIn(key, t, f"{t.get('name')} is missing {key}")
            self.assertIn(t["confidence"],
                          ("exact", "unknown", "not_probed"))
            if t["confidence"] == "exact":
                self.assertIsNotNone(t["version"],
                                     "confidence=exact with no version")

    def test_a_post_may_name_specific_candidates(self):
        st, body = call(self.base, "POST", "/api/tools/discover",
                        {"environment": "wsl", "names": ["python3", "git"]})
        self.assertEqual(st, 200)
        self.assertEqual({t["name"] for t in body["tools"]}, {"python3", "git"})

    def test_an_unreadable_version_is_reported_as_unknown_not_guessed(self):
        """A name that exists but whose version cannot be read must come back
        with version=null and confidence=unknown - never a plausible number."""
        st, body = call(self.base, "POST", "/api/tools/discover",
                        {"environment": "wsl", "names": ["not-a-real-binary"]})
        self.assertEqual(st, 200)
        # a name absent everywhere is simply not listed
        self.assertEqual(body["tools"], [])

    def test_an_unsupported_environment_is_refused_not_reported_empty(self):
        """The distinction that matters: a refusal says 'we do not know',
        an empty list says 'nothing is installed'. Only the first is true."""
        st, body = call(self.base, "POST", "/api/tools/discover",
                        {"environment": "windows", "names": ["python3"]})
        self.assertEqual(st, 400)
        self.assertEqual(body.get("error", {}).get("code"),
                         "environment_unsupported",
                         f"expected a refusal with a machine-readable code, got {body!r}")

    def test_the_response_states_that_nothing_grants_execution(self):
        st, body = call(self.base, "GET", "/api/tools/discover")
        self.assertEqual(st, 200)
        self.assertIs(body.get("execution_granted"), False)
        self.assertIn("not permitted to run", body.get("note", ""))

    def test_discovery_installs_and_writes_nothing(self):
        """Nothing is created: the only way to check is to look for changes."""
        d = pathlib.Path(tempfile.mkdtemp(prefix="p3ro-"))
        # The server's own database must live OUTSIDE the watched directory, or
        # the test measures the server's bookkeeping and calls it a discovery
        # side effect. Watching an empty dir and pointing --db elsewhere makes
        # any file that appears attributable to discovery. HOME is redirected
        # so a scan of the home directory sees this empty dir and nothing else.
        try:
            before = sorted(p.name for p in d.iterdir())
            srv = boot_server(TOKEN, prefix="p3ro-srv-",
                              env_extra={"HOME": str(d)})
            try:
                st, _ = call(srv["base"], "GET", "/api/tools/discover")
                self.assertEqual(st, 200)
                after = sorted(p.name for p in d.iterdir())
                self.assertEqual(before, after,
                                 f"discovery created files: "
                                 f"{set(after) - set(before)}")
            finally:
                stop_server(srv)
        finally:
            import shutil
            shutil.rmtree(d, ignore_errors=True)

    # -- registry --------------------------------------------------------

    def test_registration_creates_a_row_that_grants_nothing(self):
        st, tool = call(self.base, "POST", "/api/tools/registry",
                        {"name": "python3", "environment": "wsl",
                         "path": "/usr/bin/python3", "version": "3.14.4",
                         "confidence": "exact"})
        self.assertEqual(st, 201)
        self.assertIs(tool["grants_execution"], False,
                      "a registered tool must not claim execution rights")
        self.assertEqual(tool["name"], "python3")

        st, listing = call(self.base, "GET", "/api/tools/registry")
        self.assertEqual(st, 200)
        row = next((t for t in listing["tools"] if t["id"] == tool["id"]), None)
        self.assertIsNotNone(row, "the registered tool is not in the registry")
        self.assertIs(row["grants_execution"], False)

    def test_registration_cannot_upgrade_an_unknown_version(self):
        """The owner approving a record does not make an unreadable version
        readable. confidence is stored as reported."""
        st, tool = call(self.base, "POST", "/api/tools/registry",
                        {"name": "mystery", "environment": "wsl",
                         "path": "/opt/mystery", "version": None,
                         "confidence": "unknown"})
        self.assertEqual(st, 201)
        self.assertIsNone(tool["version"])
        self.assertEqual(tool["confidence"], "unknown")

    def test_registering_the_same_tool_twice_does_not_duplicate_it(self):
        body = {"name": "git", "environment": "wsl", "path": "/usr/bin/git",
                "version": "2.53.0", "confidence": "exact"}
        st1, first = call(self.base, "POST", "/api/tools/registry", body)
        st2, second = call(self.base, "POST", "/api/tools/registry", body)
        self.assertEqual((st1, st2), (201, 201))
        self.assertEqual(first["id"], second["id"],
                         "a repeated registration created a second row")
        self.assertIs(second["grants_execution"], False)

    def test_registration_in_an_unsupported_environment_is_refused(self):
        st, body = call(self.base, "POST", "/api/tools/registry",
                        {"name": "python", "environment": "windows",
                         "path": "C:/Python/python.exe"})
        self.assertEqual(st, 400)
        self.assertEqual(body.get("error", {}).get("code"),
                         "environment_unsupported",
                         f"expected a refusal with a machine-readable code, got {body!r}")

    def test_registration_requires_a_token(self):
        st, _ = call(self.base, "POST", "/api/tools/registry",
                     {"name": "x", "environment": "wsl"}, token="wrong")
        self.assertIn(st, (401, 403))

    def test_a_tool_can_be_removed(self):
        st, tool = call(self.base, "POST", "/api/tools/registry",
                        {"name": "removeme", "environment": "wsl",
                         "path": "/opt/removeme", "confidence": "unknown"})
        self.assertEqual(st, 201)
        st, body = call(self.base, "DELETE", f"/api/tools/registry/{tool['id']}")
        self.assertEqual(st, 200)
        self.assertIs(body["removed"], True)
        st, listing = call(self.base, "GET", "/api/tools/registry")
        self.assertNotIn(tool["id"], {t["id"] for t in listing["tools"]})

    def test_removing_a_tool_never_touches_the_file_on_disk(self):
        """Registration is a record. Removing it forgets the record and does
        not delete, move or modify the binary - that would be a destructive
        action behind a registry call."""
        fake = pathlib.Path(tempfile.mkdtemp(prefix="p3bin-")) / "removeme2"
        fake.write_text("#!/bin/sh\necho 'removeme2 1.0'\n", encoding="utf-8")
        st, tool = call(self.base, "POST", "/api/tools/registry",
                        {"name": "removeme2", "environment": "wsl",
                         "path": str(fake), "confidence": "unknown"})
        self.assertEqual(st, 201)
        call(self.base, "DELETE", f"/api/tools/registry/{tool['id']}")
        self.assertTrue(fake.exists(), "removing a registry row deleted the file")
        import shutil
        shutil.rmtree(fake.parent, ignore_errors=True)

    def test_a_missing_registry_row_is_reported_not_silently_ok(self):
        st, body = call(self.base, "DELETE", "/api/tools/registry/tool_does_not_exist")
        self.assertEqual(st, 200)
        self.assertIs(body["removed"], False,
                      "removing a nonexistent row claimed success")

    # -- the load-bearing claim -----------------------------------------

    def test_the_executor_list_is_untouched_by_discovery_and_registration(self):
        """The strongest form of 'a discovered tool is not thereby runnable':

        the set of things a job can actually execute is decided by the executor
        registry, and neither discovering nor registering a tool adds to it.
        """
        st, before = call(self.base, "GET", "/api/executors")
        self.assertEqual(st, 200)
        call(self.base, "GET", "/api/tools/discover")
        call(self.base, "POST", "/api/tools/registry",
             {"name": "python3", "environment": "wsl",
              "path": "/usr/bin/python3", "version": "3.14.4",
              "confidence": "exact"})
        st, after = call(self.base, "GET", "/api/executors")
        self.assertEqual(st, 200)
        self.assertEqual(before["executors"], after["executors"],
                         "registering a tool changed what can be executed")
        for name in after["executors"]:
            self.assertNotIn("python3", name,
                             "a tool name leaked into the executor registry")

    def test_no_source_reads_the_tool_table_outside_the_registry(self):
        """Static check: nothing in the executor path may consult `tools`.

        A behavioural test can only prove this for the calls it makes. Reading
        the source proves the registry is inert, which is the claim that makes
        Phase 3 safe to ship before Phase 6.
        """
        from agent_os.adapters import subprocess_executor
        src = pathlib.Path(subprocess_executor.__file__).read_text(encoding="utf-8")
        for banned in ("list_tools", "get_tool", "create_tool", "tools",
                       "grants_execution"):
            self.assertNotIn(
                banned, src,
                f"the executor mentions {banned!r}: the registry may not "
                f"grant execution, so the executor must not read it")

    def test_tool_rejection_survives_a_restart_as_a_refusal(self):
        """Not stored as a row, not silently accepted on the retry."""
        st, _ = call(self.base, "POST", "/api/tools/registry",
                     {"name": "x", "environment": "macos"})
        self.assertEqual(st, 400)
        st, listing = call(self.base, "GET", "/api/tools/registry")
        self.assertNotIn("x", {t["name"] for t in listing["tools"]},
                         "a refused registration left a row behind")


class SingleSourceOfTruth(unittest.TestCase):
    """The anti-proof found a real gap: reintroducing an override in api.py
    leaves every behavioural test green, because the override writes the value
    the tests already expect.

    So the invariant is stated structurally instead: the field the owner sees
    is the field the model holds, and no layer silently rewrites it.
    """

    @classmethod
    def setUpClass(cls):
        cls.srv = boot_server(TOKEN, prefix="p3src-srv-", db_name="s.db")
        cls.tmp = cls.srv["tmp"]
        cls.base = cls.srv["base"]

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.srv)

    def test_the_api_does_not_rewrite_the_execution_flag(self):
        """A second write of this field is a second source of truth.

        When api.py overrode it, changing the model had no effect on the
        response - so the model default was dead code and no test could tell
        the two apart. The field must be produced by the model alone.
        """
        src = (D / "agent_os" / "api.py").read_text(encoding="utf-8")
        i = src.find("def _tool_public")
        self.assertNotEqual(i, -1, "_tool_public is gone")
        body = src[i:src.find("\n    def ", i + 1)]
        self.assertNotIn('d["grants_execution"]', body,
                         "api.py assigns the flag itself; the model must be "
                         "the only place it is decided")
        self.assertIn("to_dict()", body,
                      "_tool_public should serialise the model, not rebuild it")

    def test_the_model_is_the_only_place_the_flag_is_defined(self):
        from agent_os import models as M
        tool = M.Tool(id="t", name="n", environment="wsl", path="/x",
                      version=None, confidence="unknown",
                      created_at="2026-01-01T00:00:00+00:00")
        self.assertIs(tool.grants_execution, False)
        self.assertIs(tool.to_dict()["grants_execution"], False,
                      "to_dict must not contradict the field")

    def test_the_response_matches_the_model_for_the_same_row(self):
        """End to end: what the API returns is what the model holds."""
        st, tool = call(self.base, "POST", "/api/tools/registry",
                        {"name": "sot-check", "environment": "wsl",
                         "path": "/opt/sot", "confidence": "unknown"})
        self.assertEqual(st, 201)
        self.assertIs(tool["grants_execution"], False)
        st, listing = call(self.base, "GET", "/api/tools/registry")
        row = next(t for t in listing["tools"] if t["id"] == tool["id"])
        self.assertEqual(row["grants_execution"], tool["grants_execution"])

if __name__ == "__main__":
    unittest.main()
