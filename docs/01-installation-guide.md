# Agent OS — Installation Guide

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.11 | 3.14 |
| OS | Linux (WSL2) | Linux (WSL2) |
| RAM | 512 MB | 1 GB |
| Disk | 50 MB | 100 MB |
| Docker | Not required | For container executor |

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/mehdinikzad68/Agent-OS-Premium.git
cd Agent-OS-Premium/control-service
```

### 2. Create a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install (no dependencies)

```bash
pip install -e .
```

The project has **zero runtime dependencies** — Python standard library only.

### 4. Generate a token

```bash
python -m agent_os.cli token
```

Copy the output. You will need it to connect the dashboard.

### 5. Start the server

```bash
export AGENT_OS_TOKEN=<your-token>
python -m agent_os.cli serve --db mission-control.db --port 8470
```

### 6. Open the dashboard

Navigate to `http://127.0.0.1:8470/` in your browser.

Paste the token and press **اتصال** (Connect).

## First Run

On first start, the database is created automatically with schema version 4.
The dashboard shows:

- **Missions** — create and manage missions
- **Jobs** — propose and dispatch jobs
- **Approvals** — review and decide approval requests
- **Events** — live audit trail
- **Projects** — registered project roots
- **Tools** — discovered tools (read-only)

## Enabling the Subprocess Executor

The subprocess executor is **disabled by default**. To enable it:

```bash
python -m agent_os.cli serve --db mission-control.db \
  --enable-subprocess \
  --source-workspace /path/to/disposable/copy \
  --sandbox-root /path/to/sandboxes \
  --subprocess-timeout 120
```

## Enabling the Container Executor

The container executor provides Docker isolation (no network, read-only root,
no capabilities). It requires Docker to be installed and running.

```bash
python -m agent_os.cli serve --db mission-control.db \
  --enable-container \
  --container-image python:3.11-slim
```

## Stopping the Server

Press `Ctrl+C` in the terminal. The server shuts down gracefully, closing
the database and releasing the port.

## Troubleshooting

| Problem | Solution |
|---|---|
| "refusing to serve without a token" | Set `AGENT_OS_TOKEN` or pass `--token` |
| "address already in use" | Another instance is running; stop it or use `--port` |
| "database is locked" | Another process is holding the DB; stop other instances |
| Dashboard shows "unauthorized" | Token mismatch; regenerate and re-paste |
| Jobs stuck in `interrupted_unknown` | Worker died; reconcile manually via API or UI |
