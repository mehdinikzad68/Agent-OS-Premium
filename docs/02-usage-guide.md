# Agent OS — Usage Guide

## Concepts

### Mission

A mission is a high-level goal. It has a title, a state (`draft`, `active`,
`closed`), and contains jobs. Missions are created via the API or UI.

### Job

A job is a proposed unit of work. It specifies:
- **Executor** — which adapter runs it (e.g., `subprocess-executor`)
- **Workspace paths** — directories the job may access
- **Actions** — what the job does (e.g., `run_tests`, `lint`)
- **Command** — the exact argv to run (stored as canonical JSON)

Jobs move through states: `proposed` → `awaiting_approval` → `approved` →
`dispatched` → `completed_verified` / `completed_unverified` / `interrupted_unknown`.

### Approval

An approval is a human decision on a job. It is:
- **Single-use** — consumed atomically on first dispatch
- **Action-bound** — tied to one specific action
- **Manifest-bound** — if the job's command changes, the approval is invalidated
- **Expired** — can have a TTL; expired approvals are refused

### Evidence

Evidence is the proof that a job did what it claimed. It includes:
- `diff` — code changes
- `test_report` — test output
- `exit_code` — process exit code

Evidence is stored in the append-only event log and survives restarts.

## Daily Workflow

### 1. Create a mission

```bash
curl -X POST http://127.0.0.1:8470/api/missions \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Refactor authentication module"}'
```

### 2. Propose a job

```bash
curl -X POST http://127.0.0.1:8470/api/jobs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "mission_id": "<mission_id>",
    "title": "Run tests",
    "executor": "subprocess-executor",
    "workspace_paths": ["/home/mehdi/workspace/myproject"],
    "actions": ["run_tests"],
    "command": ["python", "-m", "unittest", "discover"]
  }'
```

### 3. Request approval

```bash
curl -X POST http://127.0.0.1:8470/api/approvals \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"job_id": "<job_id>", "expires_at": "2026-10-04T18:00:00Z"}'
```

The request body may also include a `scope` (executor, workspace paths,
actions) and an `action` to bind the grant to one action. Note that
`scope.command` is deliberately ignored — the command must come from the
job, so the scope and the job can never disagree.

### 4. Review and decide (human only)

In the dashboard, the approval appears in the **Approvals** panel. Review the
exact command, workspace paths, and actions, then click **Grant** or **Deny**.

Or via API:

```bash
curl -X POST http://127.0.0.1:8470/api/approvals/<approval_id>/decide \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"decision": "granted", "principal": "human"}'
```

### 5. Dispatch

```bash
curl -X POST http://127.0.0.1:8470/api/jobs/<job_id>/dispatch \
  -H "Authorization: Bearer <token>"
```

The server validates the approval **before** running the executor. If the
approval is missing, expired, consumed, or the manifest changed, the dispatch
is refused with HTTP 409.

### 6. View evidence

```bash
curl http://127.0.0.1:8470/api/jobs/<job_id>/evidence \
  -H "Authorization: Bearer <token>"
```

## Reconciling Interrupted Jobs

If a worker dies mid-run, the job enters `interrupted_unknown`. This is
terminal for automation — no auto-rerun. A human must reconcile:

```bash
curl -X POST http://127.0.0.1:8470/api/jobs/<job_id>/reconcile \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"final_state": "completed_verified", "note": "Manually verified the fix"}'
```

## Knowledge Docs — Planned (no HTTP endpoint)

Knowledge docs are designed as versioned documents stored in SQLite, with
conflict detection on stale revisions. The service and store layers contain
the methods (`service.create_knowledge_doc`, `store.update_knowledge_doc`),
but **no HTTP route is mapped to them**, so there is no API to call yet.
The examples below are the intended shape, not something you can run today —
POST/PUT `/api/knowledge` currently returns `404`, because the route does
not exist.

```bash
# Create
curl -X POST http://127.0.0.1:8470/api/knowledge \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"title": "Architecture", "content": "# Architecture\n..."}'

# Update (with revision check)
curl -X PUT http://127.0.0.1:8470/api/knowledge/<doc_id> \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"content": "# Architecture\n...updated...", "revision": 1}'
```

## Workflows

Workflows are templates with a DAG of nodes. Each node has an action type
and dependencies.

```bash
# Create a workflow template
curl -X POST http://127.0.0.1:8470/api/workflows \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "CI Pipeline",
    "description": "Lint, test, build",
    "inputs_schema": {},
    "default_executor": "subprocess-executor",
    "nodes": [
      {"id": "lint", "action_type": "execute_job", "depends_on": []},
      {"id": "review", "action_type": "human_approval", "depends_on": ["lint"]},
      {"id": "test", "action_type": "execute_job", "depends_on": ["review"]}
    ]
  }'

# Execute
curl -X POST http://127.0.0.1:8470/api/workflows/<template_id>/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"inputs": {}}'
```

## Graphics

Graphics are persisted visualization configurations. Create one, render it to
SVG, or export and re-import it. Supported `kind` values are `shape_2d`,
`shape_3d`, `chart`, and `diagram`.

```bash
curl -X POST http://127.0.0.1:8470/api/graphics \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Workflow DAG",
    "kind": "diagram",
    "config": {"nodes": [], "edges": []}
  }'

# Render to SVG
curl -X POST http://127.0.0.1:8470/api/graphics/<graphic_id>/render \
  -H "Authorization: Bearer <token>"
```
