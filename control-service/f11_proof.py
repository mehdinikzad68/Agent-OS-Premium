"""Behavioural proof for F11 and the two UI fixes.

Same rule as F1/F3/F5: a fix that cannot be shown to fail is not evidence.
The proof asserts on HTTP responses and on the event feed - observable facts a
caller can check - and then a mutant is applied to show the proof goes red.

What it claims:
  P1  a path with no id answers 404, never 500
  P2  refusing to activate an absent mission writes nothing to the feed
  P3  the same refusal at the service layer writes nothing
  P4  the Discover button is guarded by a token check
  P5  the diagnostics render shows the status and path it captures
"""
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

D = pathlib.Path("/home/mehdi/workspace/Agent-OS/control-service")
API = D / "agent_os" / "api.py"
SVC = D / "agent_os" / "service.py"
WEB = D / "agent_os" / "web" / "index.html"
TOKEN = "f11-proof"
PORT = "8874"

checks = []


def check(pid, claim, ok, detail=""):
    checks.append((pid, claim, bool(ok), detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {pid}  {claim}")
    if detail:
        print(f"            {detail}")


def boot():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="p11-"))
    env = dict(os.environ, AGENT_OS_TOKEN=TOKEN)
    p = subprocess.Popen(
        [sys.executable, "-B", "-m", "agent_os.cli", "serve",
         "--host", "127.0.0.1", "--port", PORT, "--db", str(tmp / "p.db")],
        cwd=str(D), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    base = f"http://127.0.0.1:{PORT}"
    end = time.time() + 40
    while time.time() < end:
        try:
            urllib.request.urlopen(base + "/api/status", timeout=2)
            return p, base, tmp
        except urllib.error.HTTPError:
            return p, base, tmp
        except Exception:
            time.sleep(0.25)
    return p, base, tmp


def call(base, path, method="GET"):
    req = urllib.request.Request(
        base + path, method=method,
        headers={"Authorization": f"Bearer {TOKEN}"},
        data=b"{}" if method == "POST" else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


# ---------------------------------------------------------------- real code
print("=" * 74)
print("the claims, against the real code")
print("=" * 74)

# P1
st_map = {}
for label, path in (("mission", "/api/missions/"), ("job", "/api/jobs/"),
                    ("approval", "/api/approvals/"), ("evidence", "/api/jobs//evidence")):
    p, base, tmp = boot()
    try:
        st, body = call(base, path)
        st_map[label] = st
        check("P1", f"GET {path} answers 404, not 500", st == 404,
              f"status={st} body={body[:60]}")
    finally:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        p.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)

# P2 and P3 on one server
p, base, tmp = boot()
try:
    st, body = call(base, "/api/events")
    virgin = json.loads(body)["events"] == []
    check("P2.0", "the feed starts empty, so P2 is a real claim", virgin,
          f"events={len(json.loads(body)['events'])}")

    st, body = call(base, "/api/missions/mission_absent/activate", "POST")
    check("P2.1", "activating an absent mission is refused with 404", st == 404,
          f"status={st}")

    st, body = call(base, "/api/events")
    blob = json.dumps(json.loads(body)["events"])
    check("P2.2", "the refusal wrote nothing to the feed",
          "mission_absent" not in blob and json.loads(body)["events"] == [],
          f"events={json.loads(body)['events']}")

    st, body = call(base, "/api/missions")
    ids = [m["id"] for m in json.loads(body)["missions"]]
    check("P2.3", "no mission row was created", "mission_absent" not in ids,
          f"missions={ids}")

    sys.path.insert(0, str(D))
    from agent_os.service import ControlService
    from agent_os.store import Store
    svc_tmp = pathlib.Path(tempfile.mkdtemp(prefix="p11svc-"))
    try:
        svc = ControlService(Store(svc_tmp / "s.db"))
        raised = False
        try:
            svc.activate_mission("mission_absent")
        except KeyError:
            raised = True
        check("P3.1", "the service layer refuses", raised)
        check("P3.2", "the service layer wrote no event",
              svc.store.list_events() == [], f"events={svc.store.list_events()}")
        check("P3.3", "the service layer created no row",
              svc.store.get_mission("mission_absent") is None)
    finally:
        shutil.rmtree(svc_tmp, ignore_errors=True)
finally:
    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    p.wait(timeout=10)
    shutil.rmtree(tmp, ignore_errors=True)

# P4 and P5
html = WEB.read_text(encoding="utf-8")
i = html.find("async function runDiscovery()")
check("P4", "Discover checks for a token before requesting",
      "if (!TOKEN)" in html[i:i + 700], "guard found in runDiscovery")
check("P5.1", "the diagnostics render shows the captured status", "r.status" in html)
check("P5.2", "the diagnostics render shows the captured path", "r.path" in html)
j = html.find('"response body was not JSON"')
check("P5.3", "the warning names the request that produced it",
      "path:" in html[j:j + 200])

passed = all(c[2] for c in checks)
print()
print(f"  {sum(1 for c in checks if c[2])}/{len(checks)} checks passed on real code")
print()
print("VERDICT:", "PROVEN" if passed else "NOT PROVEN")

# ------------------------------------------------------------------ mutants
print()
print("=" * 74)
print("anti-proof: the same claims with the guards removed")
print("=" * 74)

SEG = '''        if index >= len(parts) or not parts[index]:
            raise ApiError(404, "not_found", f"{kind} not found: no id in path")
        return parts[index]'''
SEG_OLD = '''        return parts[index]'''

ACT = '''        mission = self.store.get_mission(mission_id)
        if mission is None:
            # Checked BEFORE any write. The previous order updated the state,
            # recorded the event and logged, then asserted - so activating a
            # mission that does not exist still wrote an event to the feed, and
            # the bare `assert` raised AssertionError (a 500) instead of the
            # 404 the caller deserves. An assert also disappears under -O.
            raise KeyError(f"mission not found: {mission_id!r}")
        self.store.update_mission_state(mission_id, MissionState.ACTIVE)'''
# The record_event line sits AFTER the ACT block in the file, so replacing only
# ACT would move the check after the state update but leave the event write
# after the check - a mutant that writes nothing and is therefore equivalent.
# The real defect needs record_event to move before the check too, so the
# replacement has to cover it.
ACT_WITH_EVENT = ACT + '''
        self.store.record_event("mission_activated", {"mission_id": mission_id})'''
ACT_OLD = '''        self.store.update_mission_state(mission_id, MissionState.ACTIVE)
        self.store.record_event("mission_activated", {"mission_id": mission_id})
        mission = self.store.get_mission(mission_id)
        if mission is None:
            raise KeyError(f"mission not found: {mission_id!r}")'''

GUARD = '''  if (!TOKEN) {
    msg.textContent = t("ui.toolsNeedToken");
    btn.disabled = false;
    return;
  }
  try {'''

api_o, svc_o, web_o = (API.read_text(encoding="utf-8"),
                       SVC.read_text(encoding="utf-8"),
                       WEB.read_text(encoding="utf-8"))

red = []


def mutant(name, target, old, new):
    orig = target.read_text(encoding="utf-8")
    if old not in orig:
        print(f"  {name}: pattern missing - the code moved, re-read it")
        red.append(False)
        return
    target.write_text(orig.replace(old, new, 1), encoding="utf-8")
    try:
        p, base, tmp = boot()
        try:
            statuses = []
            for path in ("/api/missions/", "/api/jobs/", "/api/approvals/"):
                statuses.append(call(base, path)[0])
            call(base, "/api/missions/mission_absent/activate", "POST")
            ev = json.loads(call(base, "/api/events")[1])["events"]
            wrote = "mission_absent" in json.dumps(ev)
            broke = any(s == 500 for s in statuses) or wrote
            red.append(broke)
            print(f"  {name}: {'RED (claim fails)' if broke else 'still green'}")
            print(f"      statuses={statuses}  feed names the absent id={wrote}")
        finally:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            p.wait(timeout=10)
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        target.write_text(orig, encoding="utf-8")


print("M1 - the 404 guard removed from _segment")
mutant("M1", API, SEG, SEG_OLD)
print("M3 - the existence check moved back after the writes")
mutant("M3", SVC, ACT_WITH_EVENT, ACT_OLD)

m4 = WEB.read_text(encoding="utf-8")
WEB.write_text(m4.replace(GUARD, "  try {", 1), encoding="utf-8")
try:
    h = WEB.read_text(encoding="utf-8")
    i = h.find("async function runDiscovery()")
    broke = "if (!TOKEN)" not in h[i:i + 700]
    red.append(broke)
    print(f"M5 - the Discover token guard removed: "
          f"{'RED' if broke else 'still green'}")
finally:
    WEB.write_text(web_o, encoding="utf-8")

print()
print("=" * 74)
if passed and all(red):
    print("PROVEN - the claims hold on real code, and every guard can be shown")
    print("         to fail. P1/P2/P3 are the security-relevant ones: a refusal")
    print("         writes nothing, and no path answers 500.")
else:
    print("NOT PROVEN - see above. Do not describe this fix as complete.")
