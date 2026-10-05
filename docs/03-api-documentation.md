# Agent OS — API Documentation

## Base URL

```
http://127.0.0.1:8470
```

## Authentication

All `/api/*` endpoints require a Bearer token. The UI shell (`/`, `/ui`,
`/index.html`) is served without auth.

```
Authorization: Bearer <token>
```

## Response Format

All responses are JSON. Errors follow this structure:

```json
{
  "error": {
    "code": "dispatch_refused",
    "message": "approval_expired"
  }
}
```

## Status Codes

| Code | Meaning |
|---|---|
| 200 | Success |
| 400 | Bad request (validation error) |
| 401 | Unauthorized (missing/invalid token) |
| 403 | Forbidden (wrong principal) |
| 404 | Not found |
| 409 | Conflict (duplicate, dispatch refused) |
| 413 | Payload too large (>1MB) |
| 500 | Internal error |

---

## Missions

### GET /api/missions

List all missions.

**Response:** `Mission[]`

```json
[
  {
    "id": "m_abc123",
    "title": "Refactor auth",
    "state": "active",
    "created_at": "2026-10-04T12:00:00+00:00"
  }
]
```

### POST /api/missions

Create a mission.

**Body:**
```json
{"title": "Refactor auth"}
```

**Response:** `Mission`

### GET /api/missions/{id}

Get a single mission.

**Response:** `Mission`

---

## Jobs

### GET /api/jobs

List all jobs.

**Response:** `Job[]`

```json
[
  {
    "id": "j_abc123",
    "mission_id": "m_abc123",
    "title": "Run tests",
    "proposed_by": "planner",
    "executor": "subprocess-executor",
    "workspace_paths": ["/home/mehdi/workspace/myproject"],
    "actions": ["run_tests"],
    "state": "awaiting_approval",
    "attempt_no": 0,
    "manifest_hash": "sha256:abc123...",
    "command": ["python", "-m", "pytest"],
    "created_at": "2026-10-04T12:00:00+00:00",
    "updated_at": "2026-10-04T12:00:00+00:00"
  }
]
```

### POST /api/missions/{mission_id}/jobs

Propose a job.

**Body:**
```json
{
  "title": "Run tests",
  "executor": "subprocess-executor",
  "workspace_paths": ["/home/mehdi/workspace/myproject"],
  "actions": ["run_tests"],
  "command": ["python", "-m", "pytest", "-v"]
}
```

**Response:** `Job`

### GET /api/jobs/{id}

Get a single job.

**Response:** `Job`

### POST /api/jobs/{id}/request-approval

Request human approval for a job.

**Body:**
```json
{"expires_at": "2026-10-04T18:00:00Z"}
```

**Response:** `Approval`

### POST /api/jobs/{id}/dispatch

Dispatch an approved job. The server validates the approval **before**
running the executor.

**Response (success):**
```json
{
  "job_id": "j_abc123",
  "state": "dispatched",
  "attempt_no": 1
}
```

**Response (refused):** HTTP 409
```json
{
  "error": {
    "code": "dispatch_refused",
    "message": "approval_expired"
  }
}
```

### POST /api/jobs/{id}/reconcile

Reconcile an interrupted job (human only).

**Body:**
```json
{"outcome": "completed_verified", "note": "Manually verified"}
```

**Response:** `Job`

### GET /api/jobs/{id}/evidence

Get the latest persisted evidence for a job.

**Response:**
```json
{
  "job_id": "j_abc123",
  "state": "completed_verified",
  "evidence": {
    "diff": "...",
    "test_report": "...",
    "exit_code": 0
  },
  "event_seq": 42,
  "ts": "2026-10-04T12:05:00+00:00",
  "kind": "job_completed_verified"
}
```

---

## Approvals

### GET /api/approvals

List all approvals.

**Response:** `Approval[]`

```json
[
  {
    "id": "a_abc123",
    "job_id": "j_abc123",
    "decision": "granted",
    "scope": {
      "executor": "subprocess-executor",
      "workspace_paths": ["/home/mehdi/workspace/myproject"],
      "actions": ["run_tests"],
      "command": ["python", "-m", "pytest"],
      "action": "run_tests"
    },
    "requested_at": "2026-10-04T12:00:00+00:00",
    "decided_at": "2026-10-04T12:01:00+00:00",
    "decided_by": "human",
    "expires_at": "2026-10-04T18:00:00+00:00",
    "manifest_hash": "sha256:abc123...",
    "consumed_at": null
  }
]
```

### POST /api/approvals/{id}/decide

Decide an approval (human only).

**Body:**
```json
{"decision": "granted", "principal": "human"}
```

**Response:** `Approval`

---

## Projects

### GET /api/projects

List registered projects.

**Response:** `Project[]`

### POST /api/projects

Register a project root.

**Body:**
```json
{"name": "myproject", "environment": "wsl", "root": "/home/mehdi/workspace/myproject"}
```

**Response:** `Project`

### DELETE /api/projects/{id}

Remove a project.

**Response:** `{"removed": true}`

---

## Tools

### GET /api/tools

List discovered tools (read-only, grants no execution).

**Response:** `Tool[]`

### POST /api/tools/scan

Trigger a tool discovery scan. Writes nothing; only probes.

**Response:** `{"scanned": true, "tools_found": 7}`

---

## Workflows

### GET /api/workflows

List workflow templates.

### POST /api/workflows

Create a workflow template.

**Body:**
```json
{
  "title": "CI Pipeline",
  "description": "Lint, test, build",
  "inputs_schema": {},
  "default_executor": "subprocess-executor",
  "nodes": [
    {"id": "lint", "action_type": "lint", "depends_on": []},
    {"id": "test", "action_type": "run_tests", "depends_on": ["lint"]}
  ]
}
```

### POST /api/workflows/{id}/execute

Execute a workflow.

**Body:**
```json
{"inputs": {}}
```

**Response:** `WorkflowExecution`

---

## Knowledge

### GET /api/knowledge

List knowledge docs.

### POST /api/knowledge

Create a knowledge doc.

**Body:**
```json
{"title": "Architecture", "content": "# Architecture\n..."}
```

### PUT /api/knowledge/{id}

Update a knowledge doc (with revision check).

**Body:**
```json
{"content": "# Architecture\n...updated...", "revision": 1}
```

---

## Graphics

### POST /api/graphics

Create a graphic.

**Body:**
```json
{
  "title": "Workflow DAG",
  "kind": "flowchart",
  "config": {"nodes": [...], "edges": [...]}
}
```

**Response:** `Graphic`

---

## Events

### GET /api/events

List events (append-only audit log).

**Query params:** `limit` (default 100), `offset` (default 0)

**Response:** `Event[]`

---

## Status

### GET /api/status

Server status.

**Response:**
```json
{
  "name": "agent-os",
  "version": "0.2.0",
  "executors": ["fake-executor", "subprocess-executor"],
  "db_path": "/path/to/mission-control.db"
}
```
