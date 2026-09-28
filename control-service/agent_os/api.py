"""Local HTTP API for the Agent OS control service.

Design rules (deny-by-default, per AGENT-OS-HANDOFF.md):
- Binds to loopback (127.0.0.1) only. No LAN/network exposure.
- Requires a bearer token unless explicitly run with --insecure (test/dev only).
- Reads are authenticated; writes additionally require the HUMAN principal.
- The executor registry is the only dispatch surface: unknown executor names
  are refused before any work, and real adapters are registered only when
  explicitly enabled (Phase D), never by default.

Standard library only (http.server, json, hmac.compare_digest).
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

from .models import (
    Approval,
    ApprovalDecision,
    ApprovalScope,
    CommandFormatError,
    DispatchRefused,
    Job,
    JobState,
    Mission,
    MissionState,
    Principal,
    Project,
    ProjectRejected,
    decode_command,
    utc_now,
)
from .logging_setup import get_logger, log_event
from .service import ControlService

_log = get_logger("api")

_EXECUTORS: dict[str, object] = {}


def register_executor(name: str, adapter: object) -> None:
    """Register an adapter under a name. The registry is the ONLY dispatch
    surface: names not registered here are refused before any work."""
    _EXECUTORS[name] = adapter


def unregister_executor(name: str) -> None:
    _EXECUTORS.pop(name, None)


def _iso_or_none(value) -> Optional[str]:
    return value if value is not None else None


def _job_to_dict(job: Job) -> dict:
    # `command` is stored as canonical JSON argv. Hand the caller back the argv
    # they sent, not the storage encoding: the API accepts a list, so it should
    # return a list. If the row predates the encoding fix and is unreadable,
    # return the raw stored value rather than raising - listing a job must not
    # 500 because of one bad column, and the raw value is still useful evidence.
    try:
        command = decode_command(job.command)
    except CommandFormatError:
        command = job.command
    return {
        "id": job.id,
        "mission_id": job.mission_id,
        "title": job.title,
        "proposed_by": job.proposed_by.value,
        "executor": job.executor,
        "workspace_paths": list(job.workspace_paths),
        "actions": list(job.actions),
        "state": job.state.value,
        "attempt_no": job.attempt_no,
        "manifest_hash": job.manifest_hash,
        "command": command,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


def _mission_to_dict(mission: Mission) -> dict:
    return {
        "id": mission.id,
        "title": mission.title,
        "state": mission.state.value,
        "created_at": mission.created_at,
    }


def _approval_to_dict(approval: Approval) -> dict:
    # The scope is what the human reads before granting. If it does not name
    # the command, the grant is a decision about "run_tests in /w" whose actual
    # effect is whatever argv the job carries - a decision made blind. Decode
    # for display so the reader sees argv, not the storage encoding, and fall
    # back to the raw string for a pre-fix row so listing approvals still works.
    try:
        scope_command = decode_command(approval.scope.command)
    except CommandFormatError:
        scope_command = approval.scope.command
    return {
        "id": approval.id,
        "job_id": approval.job_id,
        "decision": approval.decision.value,
        "scope": {
            "executor": approval.scope.executor,
            "workspace_paths": list(approval.scope.workspace_paths),
            "actions": list(approval.scope.actions),
            "command": scope_command,
        },
        "requested_at": approval.requested_at,
        "decided_at": approval.decided_at,
        "decided_by": approval.decided_by.value if approval.decided_by else None,
        "expires_at": _iso_or_none(
            approval.expires_at.isoformat() if approval.expires_at else None
        ),
        "manifest_hash": approval.manifest_hash,
    }




def _project_to_dict(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "environment": project.environment,
        "root": project.root,
        "canonical_root": project.canonical_root,
        "is_symlink": project.is_symlink,
        "read_only": project.read_only,
        "created_at": project.created_at,
    }


# A refused root is mostly the caller's mistake and is a 400. A root that is
# already registered is a conflict. An unconfigured scope is nobody's
# mistake - the server is not configured - so it is a 500, not a 400: saying
# "bad request" there would blame the caller for our missing configuration.
_PROJECT_REJECTIONS = {
    "duplicate": (409, "conflict", "project root is already registered"),
    "scope_unset": (
        500,
        "scope_unset",
        "server has no project scope configured; set AGENT_OS_PROJECT_SCOPE",
    ),
}


def _project_rejection(reason: str) -> tuple[int, dict]:
    status, code, message = _PROJECT_REJECTIONS.get(reason, (400, "bad_request", reason))
    # `reason` is repeated next to the prose on purpose: the browser maps a
    # refusal to a translated string by reason, and it must not have to parse
    # English or keep its own table that can drift from this one.
    return status, {"error": {"code": code, "message": message, "reason": reason}}

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class AgentOSApi:
    """Routes HTTP requests onto a ControlService + executor registry."""

    def __init__(self, service: ControlService, token: Optional[str]):
        self.service = service
        self.token = token  # None => no auth (only allowed in --insecure mode)

    # -- dispatch helpers -------------------------------------------------

    def handle(self, method: str, path: str, body: Optional[dict]) -> tuple[int, object]:
        try:
            if method == "GET":
                return self._get(path)
            if method == "POST":
                return self._post(path, body or {})
            if method == "DELETE":
                return self._delete(path)
            raise ApiError(405, "method_not_allowed", f"method {method} not allowed")
        except ApiError as e:
            return e.status, {"error": {"code": e.code, "message": e.message}}
        except KeyError as e:
            return 404, {"error": {"code": "not_found", "message": str(e)}}
        except PermissionError as e:
            return 403, {"error": {"code": "forbidden", "message": str(e)}}
        except DispatchRefused as e:
            return 409, {"error": {"code": "dispatch_refused", "message": e.reason}}
        except ProjectRejected as e:
            return _project_rejection(e.reason)
        except ValueError as e:
            return 400, {"error": {"code": "bad_request", "message": str(e)}}
        except Exception as e:  # noqa: BLE001 - last-resort guard; never leak internals
            # The response stays generic on purpose; the LOG is where the real
            # cause becomes visible. Without this the 500 was untraceable.
            log_event(
                _log,
                logging.ERROR,
                "api.internal_error",
                exc_info=True,
                error=f"{type(e).__name__}: {e}"[:500],
            )
            return 500, {"error": {"code": "internal", "message": "internal error"}}

    # -- GET ----------------------------------------------------------------

    def _get(self, path: str) -> tuple[int, object]:
        p = path.strip("/").split("/")
        if path == "/api/status":
            return 200, self._status()
        if path == "/api/missions":
            return 200, {"missions": [self._mission_public(m) for m in self._all_missions()]}
        if path.startswith("/api/missions/"):
            return 200, self._mission_public(self.service.store.get_mission(p[2]))
        if path == "/api/jobs":
            return 200, {"jobs": [self._job_public(j) for j in self._all_jobs()]}
        if path.startswith("/api/jobs/") and path.endswith("/evidence"):
            return 200, self._job_evidence(p[2])
        if path.startswith("/api/jobs/"):
            return 200, self._job_public(self.service.store.get_job(p[2]))
        if path == "/api/approvals":
            return 200, {"approvals": [self._approval_public(a) for a in self._all_approvals()]}
        if path.startswith("/api/approvals/"):
            return 200, self._approval_public(self.service.store.get_approval(p[2]))
        if path == "/api/projects":
            return 200, {"projects": [self._project_public(p) for p in self.service.list_projects()]}
        if path == "/api/events":
            return 200, {"events": self.service.store.list_events()}
        if path == "/api/executors":
            return 200, {"executors": sorted(_EXECUTORS.keys())}
        raise ApiError(404, "not_found", f"unknown route: {path}")

    # -- POST ---------------------------------------------------------------

    def _post(self, path: str, body: dict) -> tuple[int, object]:
        if path == "/api/projects":
            name = self._require_str(body, "name")
            environment = self._require_str(body, "environment")
            root = self._require_str(body, "root")
            return 201, self._project_public(
                self.service.register_project(name, environment, root)
            )
        if path == "/api/missions":
            title = self._require_str(body, "title")
            return 201, self._mission_public(self.service.create_mission(title))
        if path == "/api/jobs":
            return 201, self._job_public(self._propose(body))
        if path == "/api/approvals":
            return 201, self._approval_public(self._request_approval(body))
        if path.startswith("/api/approvals/") and path.endswith("/decide"):
            return 200, self._approval_public(self._decide(path.split("/")[3], body))
        if path.startswith("/api/missions/") and path.endswith("/activate"):
            return 200, self._mission_public(self.service.activate_mission(path.split("/")[3]))
        if path.startswith("/api/jobs/") and path.endswith("/dispatch"):
            return 200, self._dispatch(path.split("/")[3])
        if path.startswith("/api/jobs/") and path.endswith("/reconcile"):
            return 200, self._job_public(self._reconcile(path.split("/")[3], body))
        raise ApiError(404, "not_found", f"unknown route: {path}")

    # -- DELETE ---------------------------------------------------------------

    def _delete(self, path: str) -> tuple[int, object]:
        p = path.strip("/").split("/")
        if path.startswith("/api/projects/"):
            return 200, self._remove_project(p[2])
        raise ApiError(404, "not_found", f"unknown route: {path}")

    # -- action implementations -------------------------------------------

    def _require_command(self, value: object) -> list[str] | None:
        """Validate `command` at the edge, where a refusal is still cheap.

        None is allowed and means "no command": the subprocess executor fails
        closed on that, with a message asking the caller to set one. Anything
        present must be argv - a non-empty list of non-empty strings - because
        that is the only shape Popen accepts without a shell.

        Previously this was passed through unvalidated, so a caller could put a
        string, an int or a dict in the body and get a TypeError or a
        FileNotFoundError from deep inside the executor - a 500 for what is
        plainly a bad request, raised by the wrong layer. models.py annotates
        the field as Optional[str]; that annotation is not enforced anywhere
        and is not the shape that works, so it documented an intent rather than
        a constraint. Validating here is what actually constrains it.
        """
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ApiError(
                400,
                "command_not_a_list",
                "command must be a non-empty list of strings (argv), "
                f"or omitted; got {type(value).__name__}",
            )
        for i, part in enumerate(value):
            if not isinstance(part, str) or not part.strip():
                raise ApiError(
                    400,
                    "command_not_a_list",
                    f"command[{i}] must be a non-empty string; got "
                    f"{type(part).__name__}",
                )
        return list(value)

    def _propose(self, body: dict) -> Job:
        mission_id = self._require_str(body, "mission_id")
        title = self._require_str(body, "title")
        executor = self._require_str(body, "executor")
        workspace_paths = tuple(self._require_list(body, "workspace_paths"))
        actions = tuple(self._require_list(body, "actions"))
        proposed_by = Principal(body.get("proposed_by", "planner"))
        command = self._require_command(body.get("command"))
        return self.service.record_proposal(
            mission_id, title, executor, workspace_paths, actions, proposed_by,
            command=command,
        )

    def _request_approval(self, body: dict) -> Approval:
        job_id = self._require_str(body, "job_id")
        expires_at = None
        if body.get("expires_at"):
            from datetime import datetime
            expires_at = datetime.fromisoformat(body["expires_at"])
        scope = None
        if body.get("scope"):
            s = body["scope"]
            scope = ApprovalScope(
                executor=s.get("executor", ""),
                workspace_paths=tuple(s.get("workspace_paths", [])),
                actions=tuple(s.get("actions", [])),
                # `command` in the request body is IGNORED on purpose. The scope
                # is a bound the caller may propose; the command is the
                # operation itself and must come from the job. If a caller could
                # set it, the scope and the job could disagree and the human
                # would grant one thing while another runs - which is exactly
                # the blind-decision defect F1 describes, reachable from the
                # request body.
                command=None,
            )
            if "command" in s:
                # Record that the caller tried, so a client sending this cannot
                # believe it worked. Both sinks, like every other refusal here:
                # record_event is what /api/events serves (durable, queryable),
                # log_event is what the log viewer shows. Emitting only the log
                # would leave the attempt invisible to an operator reading the
                # event stream - a test caught exactly that.
                self.service.store.record_event(
                    "approval.scope_command_ignored",
                    {"job_id": job_id, "field": "scope.command"},
                )
                log_event(
                    _log,
                    logging.WARNING,
                    "approval.scope_command_ignored",
                    job_id=job_id,
                )
        return self.service.request_approval(job_id, expires_at=expires_at, scope=scope)

    def _decide(self, approval_id: str, body: dict) -> Approval:
        decision = ApprovalDecision(self._require_str(body, "decision"))
        # Authorization: only the HUMAN principal may decide.
        return self.service.decide(approval_id, decision, Principal.HUMAN)

    def _dispatch(self, job_id: str) -> dict:
        job = self.service.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        adapter = _EXECUTORS.get(job.executor)
        if adapter is None:
            raise DispatchRefused(f"unknown_executor:{job.executor}")
        receipt = self.service.dispatch(job_id, adapter)
        updated = self.service.store.get_job(job_id)
        return {
            "receipt": {
                "job_id": receipt.job_id,
                "attempt": receipt.attempt,
                "final_state": receipt.final_state.value,
                "duplicated": receipt.duplicated,
            },
            "job": self._job_public(updated) if updated else None,
        }

    def _reconcile(self, job_id: str, body: dict) -> Job:
        final_state = JobState(self._require_str(body, "final_state"))
        note = self._require_str(body, "note")
        return self.service.reconcile(job_id, final_state, Principal.HUMAN, note)

    def _remove_project(self, project_id: str) -> dict:
        if not self.service.remove_project(project_id):
            raise ApiError(404, "not_found", "project not found")
        return {"removed": True}

    # -- read helpers --------------------------------------------------------

    def _job_evidence(self, job_id: str) -> dict:
        """Latest persisted evidence for a job, read back from the append-only
        event log (survives restarts; no separate artifact store needed yet)."""
        job = self.service.store.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        latest = None
        for e in self.service.store.list_events():
            if e["kind"] in ("job_completed_verified", "job_completed_unverified") and \
                    e["payload"].get("job_id") == job_id:
                latest = e
        if latest is None or "evidence" not in latest["payload"]:
            return {
                "job_id": job_id, "state": job.state.value, "evidence": None,
                "note": "no persisted evidence for this job",
            }
        return {
            "job_id": job_id,
            "state": job.state.value,
            "evidence": latest["payload"]["evidence"],
            "event_seq": latest["seq"],
            "ts": latest["ts"],
            "kind": latest["kind"],
        }

    def _status(self) -> dict:
        return {
            "name": "agent-os",
            "version": "0.2.0",
            "executors": sorted(_EXECUTORS.keys()),
            "db_path": self.service.store.db_path,
        }

    def _all_missions(self) -> list[Mission]:
        rows = self.service.store.conn.execute("SELECT id FROM missions ORDER BY created_at").fetchall()
        missions = []
        for r in rows:
            m = self.service.store.get_mission(r["id"])
            if m is not None:
                missions.append(m)
        return missions

    def _all_jobs(self) -> list[Job]:
        rows = self.service.store.conn.execute("SELECT id FROM jobs ORDER BY created_at").fetchall()
        jobs = []
        for r in rows:
            j = self.service.store.get_job(r["id"])
            if j is not None:
                jobs.append(j)
        return jobs

    def _all_approvals(self) -> list[Approval]:
        rows = self.service.store.conn.execute("SELECT id FROM approvals ORDER BY requested_at").fetchall()
        approvals = []
        for r in rows:
            a = self.service.store.get_approval(r["id"])
            if a is not None:
                approvals.append(a)
        return approvals

    def _mission_public(self, mission: Optional[Mission]) -> dict:
        if mission is None:
            raise KeyError("mission not found")
        return _mission_to_dict(mission)

    def _job_public(self, job: Optional[Job]) -> dict:
        if job is None:
            raise KeyError("job not found")
        return _job_to_dict(job)

    def _project_public(self, project: Project) -> dict:
        return _project_to_dict(project)

    def _approval_public(self, approval: Optional[Approval]) -> dict:
        if approval is None:
            raise KeyError("approval not found")
        return _approval_to_dict(approval)

    # -- input validation ---------------------------------------------------

    @staticmethod
    def _require_str(body: dict, key: str) -> str:
        v = body.get(key)
        if not isinstance(v, str) or not v.strip():
            raise ApiError(400, "bad_request", f"field '{key}' must be a non-empty string")
        return v

    @staticmethod
    def _require_list(body: dict, key: str) -> list:
        v = body.get(key)
        if not isinstance(v, list):
            raise ApiError(400, "bad_request", f"field '{key}' must be a list")
        return v


def make_handler(api: AgentOSApi, token: Optional[str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AgentOS/0.2"
        protocol_version = "HTTP/1.1"
        MAX_BODY = 1_000_000  # bytes; larger requests are refused with 413

        def _authorize(self) -> bool:
            if token is None:
                return True  # --insecure mode
            header = self.headers.get("Authorization", "")
            provided = header[7:] if header.startswith("Bearer ") else ""
            return hmac.compare_digest(provided.encode(), token.encode())

        def _send(self, status: int, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _timed(self, method: str) -> None:
            # The single point where a request is recorded. It sits on
            # do_GET/do_POST rather than on _route, because the UI shell is
            # served without a token and never reaches the router.
            self._resp_status = None
            started = time.perf_counter()
            try:
                self._route(method)
            finally:
                log_event(
                    _log,
                    logging.DEBUG,
                    "http.request",
                    method=method,
                    path=self.path,
                    status=getattr(self, "_resp_status", None),
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                )

        def send_response(self, code, message=None):  # noqa: D102
            # http.server keeps the status code in a local, not on self,
            # which is why the first version of the request log recorded
            # status=None for every single line.
            self._resp_status = code
            super().send_response(code, message)

        def _route(self, method: str) -> None:
            # The static UI shell is served without a bearer token: a browser
            # navigating to the loopback URL cannot send an Authorization
            # header. The shell contains no secrets; every /api/* endpoint
            # below still requires the token.
            if method == "GET" and self.path in ("/", "/ui", "/index.html"):
                self._serve_ui()
                return
            if not self._authorize():
                self._send(401, {"error": {"code": "unauthorized", "message": "missing or invalid token"}})
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            # Hard cap on request bodies (local single-user, but cheap and
            # worth having): refuse oversized payloads before parsing.
            if length > Handler.MAX_BODY:
                self.close_connection = True
                self._send(413, {"error": {"code": "payload_too_large", "message": "request body too large"}})
                return
            body = None
            if length > 0:
                raw = self.rfile.read(length)
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    self._send(400, {"error": {"code": "bad_request", "message": "invalid JSON body"}})
                    return
            status, payload = api.handle(method, self.path, body)
            self._send(status, payload)

        def do_GET(self):  # noqa: N802
            self._timed("GET")

        def _serve_ui(self) -> None:
            from pathlib import Path

            ui = Path(__file__).resolve().parent / "web" / "index.html"
            if not ui.exists():
                self._send(404, {"error": {"code": "not_found", "message": "UI not bundled"}})
                return
            data = ui.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802
            self._timed("POST")

        def do_DELETE(self):  # noqa: N802
            self._timed("DELETE")

        def log_message(self, fmt, *args):  # noqa: A003 - BaseHTTPRequestHandler API
            # Silent on purpose. The framework access line duplicates
            # _timed()'s http.request, which already carries the status and
            # the duration. Request logging lives in exactly one place.
            return

    return Handler


def serve(
    service: ControlService,
    host: str = "127.0.0.1",
    port: int = 8470,
    token: Optional[str] = None,
    insecure: bool = False,
) -> ThreadingHTTPServer:
    """Start a blocking HTTP server. Binds loopback only unless host says otherwise."""
    if token is None and not insecure:
        raise ApiError(
            500, "no_token", "refusing to serve without a token; set AGENT_OS_TOKEN or pass --insecure"
        )
    api = AgentOSApi(service, None if insecure else token)
    handler = make_handler(api, None if insecure else token)
    # The server is bound by its own constructor, so from this line the socket
    # is open. Anything that raises before the caller receives the handle
    # leaves it bound until the garbage collector notices - and a Ctrl-C in
    # that window means the port stays taken with nothing owning it, which the
    # next start then reports as "address already in use" for no visible
    # reason. So the post-bind configuration is inside the try, and the server
    # is closed if it fails.
    server = ThreadingHTTPServer((host, port), handler)
    try:
        server.daemon_threads = True
    except BaseException:
        try:
            server.server_close()
        except OSError:
            pass
        raise
    return server


def generate_token() -> str:
    return secrets.token_urlsafe(32)
