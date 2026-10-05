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
curl -X POST http://127.0.0.1:8470/api/missions/<mission_id>/jobs \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Run tests",
    "executor": "subprocess-executor",
    "workspace_paths": ["/home/mehdi/workspace/myproject"],
    "actions": ["run_tests"],
    "command": ["python", "-m", "pytest", "-v"]
  }'
```

### 3. Request approval

```bash
curl -X POST http://127.0.0.1:8470/api/jobs/<job_id>/request-approval \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"expires_at": "2026-10-04T18:00:00Z"}'
```

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
  -d '{"outcome": "completed_verified", "note": "Manually verified the fix"}'
```

## Knowledge Docs

Knowledge docs are versioned documents stored in SQLite. They support
conflict detection — editing a stale revision raises a conflict.

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
      {"id": "lint", "action_type": "lint", "depends_on": []},
      {"id": "test", "action_type": "run_tests", "depends_on": ["lint"]},
      {"id": "build", "action_type": "build", "depends_on": ["test"]}
    ]
  }'

# Execute
curl -X POST http://127.0.0.1:8470/api/workflows/<template_id>/execute \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"inputs": {}}'
```

## Graphics

Graphics are inline-SVG visualizations rendered through the API.

```bash
curl -X POST http://127.0.0.1:8470/api/graphics \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Workflow DAG",
    "kind": "flowchart",
    "config": {"nodes": [...], "edges": [...]}
  }'
```
