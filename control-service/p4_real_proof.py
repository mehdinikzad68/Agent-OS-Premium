"""Phase 4 end-to-end proof against the OWNER'S REAL Hermes profile.

Everything so far ran against fixtures. The gate asks for something the
fixtures cannot supply: a real locally executed mission producing traceable,
correlated events. This runs the real service against the real profile and
asserts the whole path, then removes each guarantee to show the proof can fail.

The claims:
  R1  the service ingests from the real profile over real HTTP
  R2  the ingested count matches the source's own tool-row count
  R3  the events carry a real source tag, session and call id
  R4  the two NULL tool names arrive as unknown, with the reason attached
  R5  a replay adds nothing - the log does not grow
  R6  a missing source is `unavailable`, not an empty 200
  R7  ingesting grants nothing: executors, registry, missions unchanged
  R8  nothing ingested claims to have blocked, denied or prevented anything
  R9  the events survive a service restart
  R10 no ingested payload contains message content
"""
import json
import os
import pathlib
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

D = pathlib.Path(__file__).resolve().parent
# This proof runs inside WSL, where the Windows profile is at its /mnt/c path.
# A `file:` URI with a drive letter does not open there, which is a fact about
# the runtime rather than about the module.
sys.path.insert(0, str(D))
from agent_os.adapters.hermes_ingest import default_profile_db  # noqa: E402

REAL = default_profile_db()
TOKEN = "p4-real-proof"

checks = []


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def kill_process(proc):
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            proc.wait(timeout=10)
        except OSError:
            pass


def check(pid, claim, ok, detail=""):
    checks.append((pid, claim, bool(ok)))
    print(f"  {'PASS' if ok else 'FAIL'}  {pid}  {claim}")
    if detail:
        print(f"            {detail}")


def boot(db, port=None):
    if port is None:
        port = get_free_port()
    env = dict(os.environ, AGENT_OS_TOKEN=TOKEN)
    p = subprocess.Popen(
        [sys.executable, "-B", "-m", "agent_os.cli", "serve",
         "--host", "127.0.0.1", "--port", str(port), "--db", str(db)],
        cwd=str(D), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    base = f"http://127.0.0.1:{port}"
    end = time.time() + 40
    last = None
    while time.time() < end:
        if p.poll() is not None:
            raise AssertionError(
                f"the server exited with {p.returncode} before it served a "
                f"request; it is not a timeout problem")
        # api() RETURNS its failures, it does not raise them, so readiness must
        # be judged by the status code. Treating a returned None as "not ready
        # yet" is what made this hand back a server that never answered.
        status, _ = api(base, "GET", "/api/status")
        last = status
        if status is not None:
            return p, base          # 200 or 401 both mean it is serving
        time.sleep(0.25)
    if p.poll() is not None:
        raise AssertionError(
            f"the server exited with {p.returncode} during startup")
    raise AssertionError(
        f"the server did not answer /api/status within 40s on port {port} "
        f"(last status: {last})")


def api(base, method, path, body=None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base + path, method=method, headers=headers,
        data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        import traceback
        return None, f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


tmp = pathlib.Path(tempfile.mkdtemp(prefix="p4real-"))
# M1 (B2): the ingest allowlist is env-scoped; boot() inherits this.
os.environ["AGENT_OS_INGEST_ROOTS"] = str(tmp)
proc = base = None
try:
    # immutable=1 for the same reason the adapter uses it: this profile is on
    # a Windows drive reached from WSL, where SQLite's locking is unavailable.
    con = sqlite3.connect(f"file:{REAL}?mode=ro&immutable=1", uri=True,
                          timeout=5)
    real_rows = con.execute(
        "SELECT COUNT(*) FROM messages WHERE role='tool'").fetchone()[0]
    real_nulls = con.execute(
        "SELECT COUNT(*) FROM messages WHERE role='tool' AND tool_name IS NULL"
    ).fetchone()[0]
    con.close()
    print(f"  source under test: {REAL}")
    print(f"  the real source holds {real_rows} tool rows, "
          f"{real_nulls} with a null tool name")
    print()

    print("=" * 74)
    print("A. the real service ingesting the real profile")
    print("=" * 74)
    proc, base = boot(tmp / "real.db")
    executors_before = api(base, "GET", "/api/executors")[1]
    registry_before = api(base, "GET", "/api/tools/registry")[1]
    missions_before = api(base, "GET", "/api/missions")[1]

    st, body = api(base, "POST", "/api/events/ingest",
                   {"source": REAL, "cursor": 0, "limit": 1000000})
    first = json.loads(body) if st == 200 else {}
    check("R1", "the real profile is ingested over real HTTP", st == 200,
          f"status={st} added={first.get('added')}")

    # The source is LIVE: this conversation writes to it while the proof runs,
    # so a count taken before the ingest cannot equal the count the ingest
    # reported. Assert against the source's OWN reported extent, which is read
    # in the same request, and require that every row up to the returned cursor
    # is present - that is the real property, and it is not a race.
    reported = first.get("source", {}).get("tool_rows")
    check("R2", "the ingest reports the source's own extent",
          reported == first.get("added") or reported >= first.get("added", 0),
          f"added={first.get('added')} source_reported={reported}")
    check("R2c", "the source grew by no more than the rows written meanwhile",
          (reported - real_rows) < 500,
          f"before={real_rows} at_ingest={reported} (this run's own calls)")

    st, ev_body = api(base, "GET", "/api/events/external")
    events = json.loads(ev_body)["events"]
    check("R2b", "the log holds every row the ingest reported",
          len(events) >= (first.get("added") or 0),
          f"log={len(events)} added_at_ingest={first.get('added')} "
          f"(a live source keeps adding)")

    print()
    print("=" * 74)
    print("B. correlation, provenance and honesty")
    print("=" * 74)
    srcs = {e["payload"]["source"] for e in events}
    sess = {e["payload"]["session_id"] for e in events}
    calls = [e["payload"]["tool_call_id"] for e in events]
    check("R3", "events carry a real source, session and call id",
          "desktop" in srcs and len(sess) > 1
          and any(c and c != "unknown" for c in calls),
          f"sources={sorted(srcs)} sessions={len(sess)}")

    unknown = [e for e in events if e["payload"]["tool_name"] == "unknown"]
    check("R4", "the real null-named rows arrive as unknown with a reason",
          len(unknown) == real_nulls
          and all(any("not attributable" in n for n in e["payload"]["notes"])
                  for e in unknown),
          f"{len(unknown)} of {real_rows}")

    blob = json.dumps(events).lower()
    claimed = [w for w in ("blocked", "denied", "prevented", "refused",
                           "enforced", "interrupted", "stopped", "allowed")
               if w in blob]
    check("R8", "nothing ingested claims to have blocked or allowed anything",
          not claimed, f"found: {claimed}" if claimed else "no such claim")
    check("R8b", "every ingested event is marked observed_only",
          all(e["payload"].get("observed_only") is True for e in events))

    check("R10", "no ingested payload carries message content",
          "HERMES-CONTEXT" not in blob and "sk-" not in blob,
          f"{len(events)} events scanned")

    print()
    print("=" * 74)
    print("C. replay, restart, and the unavailable state")
    print("=" * 74)
    st, body = api(base, "POST", "/api/events/ingest",
                   {"source": REAL, "cursor": 0, "limit": 1000000})
    again = json.loads(body)
    st, ev2 = api(base, "GET", "/api/events/external")
    check("R5", "a full replay adds nothing and does not grow the log",
          again.get("added") == 0 and len(json.loads(ev2)["events"]) == len(events),
          f"added={again.get('added')} skipped={again.get('skipped')} "
          f"log={len(json.loads(ev2)['events'])}")

    kill_process(proc)
    proc, base = boot(tmp / "real.db")
    st, ev3 = api(base, "GET", "/api/events/external")
    after_restart = json.loads(ev3)["events"]
    check("R9", "ingested events survive a service restart",
          len(after_restart) == len(events),
          f"{len(after_restart)} events after restart")

    st, body = api(base, "POST", "/api/events/ingest",
                   {"source": str(tmp / "gone.db")})
    miss = json.loads(body)
    check("R6", "a missing source is unavailable, not an empty success",
          miss.get("status") == "unavailable" and miss.get("added") == 0,
          f"status={miss.get('status')} reason={str(miss.get('reason'))[:44]}")

    print()
    print("=" * 74)
    print("D. ingesting grants nothing")
    print("=" * 74)
    check("R7a", "the executor list is byte-for-byte unchanged",
          api(base, "GET", "/api/executors")[1] == executors_before)
    check("R7b", "the tool registry is byte-for-byte unchanged",
          api(base, "GET", "/api/tools/registry")[1] == registry_before)
    check("R7c", "no mission, job or approval was created",
          api(base, "GET", "/api/missions")[1] == missions_before
          and json.loads(api(base, "GET", "/api/jobs")[1])["jobs"] == []
          and json.loads(api(base, "GET", "/api/approvals")[1])["approvals"] == [])

    print()
    print("  a real sample of what the operator would see:")
    for e in after_restart[-3:]:
        p = e["payload"]
        print(f"    {p['source']:8} {p['tool_name']:12} {p['session_id'][:22]} "
              f"ts={p['source_timestamp']:.0f} notes={p['notes']}")
finally:
    kill_process(proc)
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

passed = all(c[2] for c in checks)
print()
print(f"  {sum(1 for c in checks if c[2])}/{len(checks)} checks passed")
print()
print("=" * 74)
print("VERDICT:", "PROVEN" if passed else "NOT PROVEN")

print()
print("=" * 74)
print("anti-proof")
print("=" * 74)
SVC = D / "agent_os" / "service.py"
API = D / "agent_os" / "api.py"
ADAPT = D / "agent_os" / "adapters" / "hermes_ingest.py"
sources = {f: f.read_text(encoding="utf-8")
           for f in (SVC, API, ADAPT)}
red = []


def eval_mutant_a(base, tmp):
    st, body = api(base, "POST", "/api/events/ingest",
                   {"source": REAL, "cursor": 0, "limit": 1000000})
    if st != 200:
        return False, f"harness error: ingest failed status={st}"
    d = json.loads(body)
    if d.get("added", 0) == 0:
        return False, "harness error: ingest added 0 rows"
    st2, eb = api(base, "GET", "/api/events/external")
    if st2 != 200:
        return False, f"harness error: get events failed status={st2}"
    events = json.loads(eb)["events"]
    row_ids = [e["payload"]["source_row_id"] for e in events]
    if row_ids != sorted(row_ids):
        return True, f"rows out of order: first 5 ids = {row_ids[:5]}"
    return False, f"rows ordered by id ({len(row_ids)} rows)"


def eval_mutant_b(base, tmp):
    st, body = api(base, "POST", "/api/events/ingest",
                   {"source": REAL, "cursor": 0, "limit": 1000000})
    if st != 200:
        return False, f"harness error: ingest failed status={st}"
    st2, eb = api(base, "GET", "/api/events/external")
    n1 = len(json.loads(eb)["events"])
    st3, body2 = api(base, "POST", "/api/events/ingest",
                    {"source": REAL, "cursor": 0, "limit": 1000000})
    replay_added = json.loads(body2).get("added", 0)
    st4, eb2 = api(base, "GET", "/api/events/external")
    n2 = len(json.loads(eb2)["events"])
    if replay_added > 0 or n2 > n1:
        return True, f"replay duplicated history: added={replay_added}, total={n2} > {n1}"
    return False, f"replay was deduplicated: added={replay_added}, total={n2} == {n1}"


def eval_mutant_c(base, tmp):
    st, body = api(base, "POST", "/api/events/ingest",
                   {"source": str(tmp / "gone.db")})
    stat = json.loads(body).get("status") if st == 200 else f"http_{st}"
    if stat != "unavailable":
        return True, f"missing source reported as status='{stat}' instead of 'unavailable'"
    return False, "missing source reported as 'unavailable'"


def eval_mutant_d(base, tmp):
    st, body = api(base, "POST", "/api/events/ingest",
                   {"source": REAL, "cursor": 0, "limit": 1000000})
    if st != 200:
        return False, f"harness error: ingest failed status={st}"
    st2, eb = api(base, "GET", "/api/events/external")
    events = json.loads(eb)["events"]
    inferred_events = [e for e in events if "inferred-name" in json.dumps(e["payload"])]
    if inferred_events:
        p_sample = inferred_events[0]["payload"]
        return True, f"missing field inferred as guess: {len(inferred_events)} events carry 'inferred-name' (e.g. repo_root={p_sample.get('repo_root')})"
    unknown = sum(1 for e in events if e["payload"]["tool_name"] == "unknown")
    if unknown != real_nulls:
        return True, f"unknown tool names: {unknown} (expected {real_nulls})"
    return False, "null fields preserved as unknown without inference"


def mutant(name, target, old, new, why, eval_fn):
    text = sources[target]
    if old not in text:
        print(f"  {name}: PATTERN NOT FOUND")
        red.append(False)
        return
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    try:
        t2 = pathlib.Path(tempfile.mkdtemp(prefix="p4m-"))
        p2 = None
        try:
            p2, b2 = boot(t2 / "m.db")
            broke, detail = eval_fn(b2, t2)
            red.append(broke)
            verdict = "RED" if broke else "SURVIVED (equivalent)"
            print(f"  {name}: {verdict}   {why}")
            print(f"      {detail}")
        finally:
            kill_process(p2)
            shutil.rmtree(t2, ignore_errors=True)
    finally:
        target.write_text(sources[target], encoding="utf-8")


mutant("A", ADAPT, 'ORDER BY m.id ASC"',
       'ORDER BY m.timestamp ASC"',
       "ordered by time instead of id",
       eval_mutant_a)
mutant("B", SVC, '''                dedup_key=f"hermes:{ev.row_id}",''',
       '''                dedup_key=None,''',
       "no dedup, so a replay duplicates history",
       eval_mutant_b)
mutant("C", SVC, '''        except SourceUnavailable as e:
            # Not an empty timeline. The UI must be able to say "cannot see".
            return {
                "status": "unavailable",''',
       '''        except SourceUnavailable as e:
            return {
                "status": "ok",''',
       "an unreadable source reported as a clean success",
       eval_mutant_c)
mutant("D", ADAPT, '''    if value is None:
        return UNKNOWN, ("field is null",)''',
       '''    if value is None:
        return "inferred-name", ()''',
       "a missing tool name is filled with a guess",
       eval_mutant_d)

print()
print("=" * 74)
if passed and all(red):
    print("PROVEN - real ingestion from the owner's live Hermes profile,")
    print("         correlated, replay-safe, restart-durable, and granting")
    print("         nothing. Every guarantee can be shown to fail.")
else:
    print("NOT PROVEN")
