"""SQLite operational truth.

Rules encoded here (AGENT-OS-HANDOFF.md section 7, memory model):
- The event log is APPEND-ONLY: this module exposes no update/delete
  for events. Duplicated dedup_keys are ignored (idempotent replay).
- Only the control service writes authoritative state. Agents propose;
  they never write job/mission/approval rows directly.
- Durability: standard sqlite with journal mode WAL and synchronous=FULL.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import (
    Approval,
    ApprovalDecision,
    ApprovalScope,
    Job,
    JobState,
    Mission,
    MissionState,
    Principal,
    iso,
    utc_now,
)

SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS missions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  mission_id TEXT NOT NULL,
  title TEXT NOT NULL,
  proposed_by TEXT NOT NULL,
  executor TEXT NOT NULL,
  workspace_paths TEXT NOT NULL,
  actions TEXT NOT NULL,
  state TEXT NOT NULL,
  attempt_no INTEGER NOT NULL DEFAULT 0,
  manifest_hash TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  command TEXT
);
CREATE TABLE IF NOT EXISTS approvals (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  scope_json TEXT NOT NULL,
  requested_at TEXT NOT NULL,
  decided_at TEXT,
  decided_by TEXT,
  expires_at TEXT,
  manifest_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  dedup_key TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS knowledge_docs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0,
  content TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

# Migrations applied in order when an existing DB has an older schema_version.
# Each entry is a (from_version, list_of_sql_statements).
_MIGRATIONS: dict[int, list[str]] = {
    # v1 -> v2: add the optional `command` column to jobs (subprocess executor).
    1: [
        "ALTER TABLE jobs ADD COLUMN command TEXT",
    ],
}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        # check_same_thread=False + a lock: the HTTP server runs handlers on
        # worker threads while the connection is opened on the main thread.
        # The lock serializes all DB access (single-writer control plane).
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # -- schema ---------------------------------------------------------

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(_SCHEMA)
            current = self._schema_version()
            if current < SCHEMA_VERSION:
                self._migrate(current)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def _schema_version(self) -> int:
        """Stored schema version. A missing row means a fresh DB that was
        just created by _SCHEMA at the LATEST version (no migration needed)."""
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            return SCHEMA_VERSION
        try:
            return int(row["value"])
        except (ValueError, TypeError):
            return SCHEMA_VERSION

    def _migrate(self, from_version: int) -> None:
        v = from_version
        while v < SCHEMA_VERSION:
            if v in _MIGRATIONS:
                for stmt in _MIGRATIONS[v]:
                    self.conn.execute(stmt)
            v += 1

    # -- missions -------------------------------------------------------

    def create_mission(self, title: str, now: Optional[datetime] = None) -> Mission:
        with self._lock:
            mission = Mission(
                id=_new_id("mission"),
                title=title,
                state=MissionState.DRAFT,
                created_at=iso(now or utc_now()),
            )
            with self.conn:
                self.conn.execute(
                    "INSERT INTO missions (id, title, state, created_at) VALUES (?,?,?,?)",
                    (mission.id, mission.title, mission.state.value, mission.created_at),
                )
        return mission

    def get_mission(self, mission_id: str) -> Optional[Mission]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM missions WHERE id=?", (mission_id,)
            ).fetchone()
            if row is None:
                return None
            return Mission(
                id=row["id"],
                title=row["title"],
                state=MissionState(row["state"]),
                created_at=row["created_at"],
            )

    def update_mission_state(self, mission_id: str, state: MissionState) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "UPDATE missions SET state=? WHERE id=?", (state.value, mission_id)
                )

    # -- jobs -----------------------------------------------------------

    def insert_job(self, job: Job) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO jobs (id, mission_id, title, proposed_by, executor,"
                    " workspace_paths, actions, state, attempt_no, manifest_hash,"
                    " created_at, updated_at, command) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        job.id, job.mission_id, job.title, job.proposed_by.value,
                        job.executor, json.dumps(list(job.workspace_paths)),
                        json.dumps(list(job.actions)), job.state.value,
                        job.attempt_no, job.manifest_hash, job.created_at, job.updated_at,
                        job.command,
                    ),
                )

    def get_job(self, job_id: str) -> Optional[Job]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                return None
            return Job(
                id=row["id"],
                mission_id=row["mission_id"],
                title=row["title"],
                proposed_by=Principal(row["proposed_by"]),
                executor=row["executor"],
                workspace_paths=tuple(json.loads(row["workspace_paths"])),
                actions=tuple(json.loads(row["actions"])),
                state=JobState(row["state"]),
                attempt_no=row["attempt_no"],
                manifest_hash=row["manifest_hash"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                command=row["command"],
            )

    def update_job(
        self,
        job_id: str,
        state: Optional[JobState] = None,
        attempt_no: Optional[int] = None,
        manifest_hash: Optional[str] = None,
        command: Optional[str] = None,
    ) -> None:
        with self._lock:
            sets: list[str] = []
            args: list = []
            if state is not None:
                sets.append("state=?")
                args.append(state.value)
            if attempt_no is not None:
                sets.append("attempt_no=?")
                args.append(attempt_no)
            if manifest_hash is not None:
                sets.append("manifest_hash=?")
                args.append(manifest_hash)
            if command is not None:
                sets.append("command=?")
                args.append(command)
            if not sets:
                return
            sets.append("updated_at=?")
            args.append(iso(utc_now()))
            args.append(job_id)
            with self.conn:
                self.conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", args)

    # -- approvals ------------------------------------------------------

    def insert_approval(self, approval: Approval) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO approvals (id, job_id, decision, scope_json, requested_at,"
                    " decided_at, decided_by, expires_at, manifest_hash)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        approval.id, approval.job_id, approval.decision.value,
                        json.dumps(
                            {
                                "executor": approval.scope.executor,
                                "workspace_paths": list(approval.scope.workspace_paths),
                                "actions": list(approval.scope.actions),
                            }
                        ),
                        approval.requested_at, approval.decided_at,
                        approval.decided_by.value if approval.decided_by else None,
                        iso(approval.expires_at) if approval.expires_at else None,
                        approval.manifest_hash,
                    ),
                )

    def get_approval(self, approval_id: str) -> Optional[Approval]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM approvals WHERE id=?", (approval_id,)
            ).fetchone()
            return self._row_to_approval(row)

    def latest_approval_for_job(self, job_id: str) -> Optional[Approval]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM approvals WHERE job_id=? ORDER BY requested_at DESC, rowid DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            return self._row_to_approval(row)

    def update_approval_decision(
        self,
        approval_id: str,
        decision: ApprovalDecision,
        decided_at: str,
        decided_by: Principal,
    ) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "UPDATE approvals SET decision=?, decided_at=?, decided_by=? WHERE id=?",
                    (decision.value, decided_at, decided_by.value, approval_id),
                )

    @staticmethod
    def _row_to_approval(row: Optional[sqlite3.Row]) -> Optional[Approval]:
        if row is None:
            return None
        scope_raw = json.loads(row["scope_json"])
        return Approval(
            id=row["id"],
            job_id=row["job_id"],
            decision=ApprovalDecision(row["decision"]),
            scope=ApprovalScope(
                executor=scope_raw["executor"],
                workspace_paths=tuple(scope_raw["workspace_paths"]),
                actions=tuple(scope_raw["actions"]),
            ),
            requested_at=row["requested_at"],
            decided_at=row["decided_at"],
            decided_by=Principal(row["decided_by"]) if row["decided_by"] else None,
            expires_at=(
                datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None
            ),
            manifest_hash=row["manifest_hash"],
        )

    # -- events (append-only) --------------------------------------------

    def record_event(
        self, kind: str, payload: dict, dedup_key: Optional[str] = None
    ) -> bool:
        """Append an event. Returns False when the dedup_key already
        exists (idempotent replay: no duplicate row, no duplicate action)."""
        with self._lock:
            try:
                with self.conn:
                    self.conn.execute(
                        "INSERT INTO events (ts, kind, payload_json, dedup_key)"
                        " VALUES (?,?,?,?)",
                        (iso(utc_now()), kind, json.dumps(payload, sort_keys=True), dedup_key),
                    )
                return True
            except sqlite3.IntegrityError:
                return False

    def list_events(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT seq, ts, kind, payload_json, dedup_key FROM events ORDER BY seq"
            ).fetchall()
            return [
                {
                    "seq": r["seq"],
                    "ts": r["ts"],
                    "kind": r["kind"],
                    "payload": json.loads(r["payload_json"]),
                    "dedup_key": r["dedup_key"],
                }
                for r in rows
            ]

    # -- knowledge (Obsidian-style revisioned docs, skeleton form) -------

    def create_knowledge_doc(self, doc_id: str, title: str, content: str) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "INSERT INTO knowledge_docs (id, title, revision, content, updated_at)"
                    " VALUES (?,?,0,?,?)",
                    (doc_id, title, content, iso(utc_now())),
                )

    def get_knowledge_doc(self, doc_id: str) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM knowledge_docs WHERE id=?", (doc_id,)
            ).fetchone()
            if row is None:
                return None
            return {
                "id": row["id"],
                "title": row["title"],
                "revision": row["revision"],
                "content": row["content"],
                "updated_at": row["updated_at"],
            }

    def update_knowledge_doc(self, doc_id: str, revision: int, content: str) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "UPDATE knowledge_docs SET revision=?, content=?, updated_at=? WHERE id=?",
                    (revision, content, iso(utc_now()), doc_id),
                )
