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
    DispatchRefused,
    Job,
    JobState,
    Mission,
    MissionState,
    Principal,
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
        "command": job.command,
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
    return {
        "id": approval.id,
        "job_id": approval.job_id,
        "decision": approval.decision.value,
        "scope": {
            "executor": approval.scope.executor,
            "workspace_paths": list(approval.scope.workspace_paths),
            "actions": list(approval.scope.actions),
        },
        "requested_at": approval.requested_at,
        "decided_at": approval.decided_at,
        "decided_by": approval.decided_by.value if approval.decided_by else None,
        "expires_at": _iso_or_none(
            approval.expires_at.isoformat() if approval.expires_at else None
        ),
        "manifest_hash": approval.manifest_hash,
    }


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
            raise ApiError(405, "method_not_allowed", f"method {method} not allowed")
        except ApiError as e:
            return e.status, {"error": {"code": e.code, "message": e.message}}
        except KeyError as e:
            return 404, {"error": {"code": "not_found", "message": str(e)}}
        except PermissionError as e:
            return 403, {"error": {"code": "forbidden", "message": str(e)}}
        except DispatchRefused as e:
            return 409, {"error": {"code": "dispatch_refused", "message": e.reason}}
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
        if path == "/api/events":
            return 200, {"events": self.service.store.list_events()}
        if path == "/api/executors":
            return 200, {"executors": sorted(_EXECUTORS.keys())}
        raise ApiError(404, "not_found", f"unknown route: {path}")

    # -- POST ---------------------------------------------------------------

    def _post(self, path: str, body: dict) -> tuple[int, object]:
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

    # -- action implementations -------------------------------------------

    def _propose(self, body: dict) -> Job:
        mission_id = self._require_str(body, "mission_id")
        title = self._require_str(body, "title")
        executor = self._require_str(body, "executor")
        workspace_paths = tuple(self._require_list(body, "workspace_paths"))
        actions = tuple(self._require_list(body, "actions"))
        proposed_by = Principal(body.get("proposed_by", "planner"))
        command = body.get("command")
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
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def generate_token() -> str:
    return secrets.token_urlsafe(32)
