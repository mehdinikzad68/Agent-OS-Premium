# Agent OS — Operations Runbook (v0.2.0)

Single-user, local, loopback-only. No containers or system services required.

## 1. Start / stop

```bat
cd control-service
set AGENT_OS_TOKEN=<token from "agent_os.cli token">
python -m agent_os.cli serve --db mission-control.db --port 8470
```

- Stop: `Ctrl+C` (graceful; `server.server_close()` + store close run in `finally`).
- Refuses to start without a token unless `--insecure` (dev only — never for real data).

## 2. Token management

- Generate: `python -m agent_os.cli token`
- Source: `--token` arg > `AGENT_OS_TOKEN` env var > refuse to serve.
- Rotate: generate a new token, restart the server, update the dashboard field
  (it is re-sent as `Authorization: Bearer …` on every request).
- Storage: the UI keeps the token in browser `localStorage` for this origin only.
  **Never** put tokens in the DB, Obsidian, or any artifact file.

## 3. Enabling the subprocess executor (explicit gate)

```bat
python -m agent_os.cli serve --db mission-control.db ^
  --enable-subprocess ^
  --source-workspace D:\path\to\disposable\copy\source ^
  --sandbox-root D:\path\control-service\sandboxes ^
  --subprocess-timeout 120 [--keep-sandbox]
```

Rules enforced by design:
- The command runs only in a **fresh disposable copy** of `--source-workspace`;
  the source tree is never modified (tested).
- `command` is part of the job manifest hash → changing it invalidates the grant.
- Timeout kills the process and reports `reason=timeout` — **never** success.
- Sandbox cleanup: directories are removed after each run unless `--keep-sandbox`.
  If a sandbox cannot be removed (ACL/lock), inspect and delete manually.
- `exit 0` without a recognizable test signal ⇒ `completed_unverified`, not verified.

## 4. Backup & recovery

- The **only** authoritative state is the SQLite file (`--db` path, WAL mode).
- Backup: stop the server, copy `*.db` (plus `-wal`/`-shm` if present) anywhere.
  Consistent even hot-copy: `python -c "import sqlite3;sqlite3.connect('mission-control.db').execute('PRAGMA wal_checkpoint(TRUNCATE)')"`.
- Restore: put the file back and start the server. Schema migrations run
  automatically on open (v1→v2 adds `jobs.command`; future versions append steps).
- Corruption: run `sqlite3 mission-control.db "PRAGMA integrity_check;"`.
  The append-only `events` table is the audit truth — never edit it.

## 5. Inspecting evidence

- `GET /api/jobs/{id}/evidence` returns the latest persisted evidence
  (`diff`, `test_report`, `exit_code`) read back from the append-only event log,
  plus the event `seq`/`ts` and the completion `kind`. It survives restarts.
- Evidence written into events is truncated at 16 KB per string; the executor
  captures at most 64 KB per stream. Very large outputs are deliberately lost —
  there is no artifact store yet (see READINESS.md).
- In the dashboard, select a job to see its detail panel: state, attempt,
  manifest hash, command, evidence blocks, and the action buttons appropriate to
  the state (request approval / dispatch / reconcile).

## 6. Incident handling

| Symptom | Meaning | Action |
|---|---|---|
| Job stuck `interrupted_unknown` | worker died mid-run; outcome unknown | Inspect evidence, then `POST /api/jobs/{id}/reconcile` with `failed`/`completed_*` + note (human-only; auto-rerun is forbidden by design) |
| `409 dispatch_refused` | policy denied before execution | Read `reason` (`approval_expired`, `destination_not_approved`, `manifest_changed…`, `unknown_executor…`); re-approve after fixing scope |
| `401` on API calls | token mismatch | Regenerate/rotate token; check `AGENT_OS_TOKEN` |
| Server exits at startup, "refusing to serve without a token" | fail-closed by design | Set token or add `--insecure` (dev only) |
| Port already in use | previous instance alive | Stop it, or pass `--port <other>` |

## 7. Upgrade

1. Stop server. 2. Backup DB (§4). 3. Deploy new code. 4. Start — migrations apply.
5. Run `run_tests.py` + `e2e_verify.py` + `check_ui.py`; all must exit 0 before
   keeping the upgrade.

## 8. Explicit non-capabilities (by design)

- No merge/publish/deploy actions anywhere.
- No network egress from the control plane; executors run loopback-only by policy.
- No multi-user, no remote binding (unless you deliberately pass another `--host`),
  no credential handling. Re-enabling these requires separate, explicit decisions.
