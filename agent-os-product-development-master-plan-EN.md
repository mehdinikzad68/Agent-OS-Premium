# Agent OS — Product Development Master Plan

**Document status:** Planning baseline for Hermes and the human owner  
**Date:** 2026-09-26  
**Language of this document:** English  
**Project intent:** Build a dependable local-first control plane for AI agents, first for its owner's daily use, then—only after validation—as a product for other agentic-AI users.  
**Operating rule:** Work on exactly one scoped item at a time. Never infer permission to change a repository, host, container, or external account from this document.

## 1. Executive brief

Agent OS should let a human observe real agent activity, understand why an action is proposed, and intervene before sensitive actions occur, while allowing approved low-risk work to continue autonomously. Its experience should feel like a futuristic mission-control room: a beautiful spatial workflow view backed by reliable events and ordinary, readable controls. It must be configurable rather than tied to the owner's machine, projects, tools, or paths.

The owner uses Hermes Desktop on Windows 11 as the principal coordinator; Hermes calls DeepSeek Harness (DSH) for coding in Ubuntu 26.04 on WSL2. Antigravity IDE is used for editing. Docker Desktop is installed on Windows with WSL integration enabled for Ubuntu-26.04. The owner's WordPress development project is at `/home/mehdi/workspace/wp-bioscentiran` in WSL and currently has WordPress and MariaDB containers under the `wp-bioscentiran` Compose project. These are **example discovery targets**, not hard-coded product defaults. Protect existing project data and containers. Agent OS should be developed locally, run and used while being developed, and kept private until the owner deliberately chooses to publish the new product.

The planned UI supports English (`en`, default, LTR) and Persian (`fa`, RTL). The approved visual concept is a dark, futuristic control room with a central spatial relationship view, readable two-dimensional approval panels, and an operational timeline. It is a visual direction, not an implementation specification or a claim that all depicted integrations already work.

## 2. Current baseline and explicit unknowns

Previous repository inspection identified `mehdinikzad68/Agent-OS` on GitHub, a Python `control-service` package with `api.py`, `cli.py`, `models.py`, `policy.py`, `service.py`, `store.py`, `adapters/`, and `web/index.html`, plus tests and local verification scripts. Commit messages describe a v0.2.0 release and passing tests. **Do not treat commit messages as proof of the current working tree or runtime behavior.** Re-inspect files locally, run tests, and record results. The existing repository was observed as public; check its visibility again before any push. A feature branch in a public repository is not a privacy boundary.

Unknowns that must be resolved by read-only investigation, not assumption: actual API and state contracts; the current UI's dependencies and rendering behavior; how local Hermes Desktop exposes events, sessions, and control surfaces in the installed version; whether DSH provides suitable interception points in the installed version; what permissions Docker integration exposes; whether the local clone has uncommitted changes; and whether any existing tracked files or history contain secrets. No statement in this plan certifies any integration as available or secure.

## 3. Product principles and non-goals

### Principles

1. **Truth before spectacle:** Every live indicator comes from a real event, with provenance and freshness. Unknown, disconnected, historical, and simulated states must be unmistakably different.
2. **Control before autonomy:** An approval must gate the operation *before* it executes. Merely logging a dangerous action afterward is not an approval mechanism.
3. **Deny by default at boundaries:** Unknown tools, paths, permissions, network destinations, or integration failures cannot silently expand authority.
4. **Local-first and user-owned:** Work locally first. No telemetry, cloud synchronization, or external exposure by default.
5. **One capability per iteration:** Every change has a small scope, a rollback path, tests, and a human acceptance check.
6. **Technology-neutral core:** Hermes, DSH, Antigravity, WordPress, SEO tools, and future providers integrate through explicit contracts, not scattered special cases.
7. **Accessible by design:** All essential controls must work without 3D, animation, color perception, or a mouse.
8. **No secret material in public development artifacts:** Mask logs and screenshots, exclude local credentials from commits, and review staged content before any remote push.

### Non-goals for the first personal-use release

- A cloud SaaS, multi-tenant identity platform, or remote internet-facing controller.
- Universal interception of every action performed by proprietary or external agents.
- Automatic installation of detected tools or automatic mounting of arbitrary host paths.
- Claims of strong isolation solely because work occurs in WSL or a normal Docker container.
- A fully immersive 3D interface at the expense of reliable approvals or auditability.

## 4. Roles, authority, and development method

**Owner (human):** Sets goals, reviews scope and diffs, approves every sensitive host/repository action, runs or authorizes local checks, and makes release decisions.

**Hermes (coordinator):** Maintains the current task plan, delegates narrowly scoped coding to DSH, collects evidence, compares results against acceptance criteria, and reports uncertainties. It must not treat its own narrative as evidence of tool execution.

**DSH (implementation agent):** Changes only approved project files in the assigned workspace and runs allowed tests. It must return a concise change list, actual test outputs, and an explicit list of things not verified.

**Agent OS (product):** Eventually manages project/tool registration, evidence collection, policies, approvals, and visualization. During development, it is the **system under test**, not the sole mechanism for controlling its own development. Keep a manual Git/terminal recovery route.

**Human-facing review protocol for each change:** (1) read-only inventory and proposal; (2) explicit approval of bounded edits; (3) implementation and local tests; (4) show diff and failure notes; (5) owner tests in the running application; (6) owner authorizes commit/push/merge separately as appropriate. Never reinterpret approval of a plan as approval to execute a later destructive operation.

## 5. Privacy and repository strategy

Develop in the local WSL filesystem, with an independently private development repository if off-device version control is desired. The existing public repository may remain a reference or be handled separately; do not push the unreleased design or new product implementation to it. Before creating a private remote, confirm account, target name, visibility, included history, and exactly which files will be uploaded. Private hosting reduces casual access but does not replace credential hygiene or backup. Changing a previously public repository to private cannot revoke copies already obtained while public.

Required repository hygiene: ignore `.env`, credential stores, local databases, runtime state, logs containing secrets, and machine-specific configuration; include sanitized example files instead. Scan staged changes and relevant history for secrets; if a real credential was exposed, revoke/rotate it. Keep a tested offline backup/restore path for user data. Do not commit customer content or private project paths as universal defaults. Develop in small branches or worktrees only when their added complexity serves a real need.

## 6. Target architecture

```text
Human <-> Agent OS UI (English/Persian; 2D operational shell + optional 3D view)
                   |
                   v
          Local control API / identity boundary
                   |
        +----------+-----------+
        |                      |
  Project & tool registry   Policy/approval service
        |                      |
        +----------+-----------+
                   |
            Event and evidence store
                   |
        +----------+-------------------+
        |          |                   |
 Hermes adapter  DSH adapter   Docker/runtime adapter
        |          |                   |
 Windows desktop  WSL runtime       Per-project workspace
                   |
                Other adapters, added explicitly
```

This diagram separates **observation**, **decision**, and **execution**. Observers can report events without granting control. Executors can run only explicitly allowed operations. A connector's inability to intercept an operation must be surfaced in the UI, not disguised as protection.

### 6.1 Domain objects

- **Project:** Stable ID, display name, execution environment (Windows/WSL distro/container/remote), validated root path, permitted mount scope, policy profile, associated services, and status.
- **Tool:** Stable ID, kind (agent, CLI, IDE, service, runtime), installation environment and resolved executable/endpoint, discovered version, capabilities, trust level, and owner-approved registration state.
- **Mission:** Human goal, project association, owner, desired outcome, risk profile, and lifecycle.
- **Job:** Concrete unit delegated to an actor, dependency links, attempt count, timestamps, result, and provenance.
- **Event:** Immutable record with event ID, source, timestamp, receive timestamp, correlation IDs, schema version, visibility/freshness, and redaction status.
- **Approval request:** Exact proposed action, target, scope, affected files/commands, preview/diff if available, policy reason, expiration, and single-use decision token.
- **Evidence:** Bounded stdout/stderr, diffs, test results, artifact hashes, or external references, all with retention and redaction rules.

### 6.2 Event truthfulness

Use an explicit event envelope and correlation IDs across Hermes, DSH, and Agent OS. Preserve ordering information and deduplicate retries. Distinguish observed tool-start/tool-end from inferred relationships. A missing event stream becomes **unknown** or **disconnected**, never **idle** by default. No synthetic sub-agent topology should be shown as real. If local Hermes provides only partial visibility, show partial visibility and document the gap.

### 6.3 Project and tool discovery

The user selects the environment first. Project paths can be entered manually or selected via a **server-side** browser operating within the chosen WSL/Windows context. Normalize paths in that environment, validate existence and allowed root, reject traversal/symlink escape cases, and show the exact bind mount before activation. Discovery is read-only. Tool candidates can be found in the selected environment's PATH and approved locations, then probed only with an allowlisted safe version/health command and a timeout. Docker service inspection is separate from discovering a CLI. The user must explicitly register a discovered tool and assign it per-project capabilities. Detection, registration, authorization, and execution are separate states.

### 6.4 Per-project execution

For the WordPress example, leave existing WordPress and MariaDB containers intact. A separate runner may be added for agent work after validating mounts, user IDs, networking, dependencies, and rollback. Start in read-only or dry-run mode; grant minimal writes per project/task. Never mount a whole home directory, host credential directory, or Docker socket into an untrusted agent container. Treat bind-mounted project files as real host files: container writes can change the source. Secrets and sensitive project files require separate exclusion or protection; an `.env` inside a writable project mount is not protected just because it is in Docker. Container isolation is a risk-reduction layer, not a guarantee against all host or network effects.

### 6.5 Policy and approval semantics

A risk policy considers actor, tool, action, project root, canonicalized target, file sensitivity, network destination, and current run authority. Examples requiring explicit review: changes outside the approved workspace; modification/deletion of sensitive files; destructive commands; database migrations; changing container mounts; publishing content; `git push`; and credential exposure. Unknown or unverifiable actions fail closed. Approval must bind to an exact action identity and content hash, have a TTL and single-use semantics, and be re-requested if the command, file set, diff, or destination changes. Handle timeouts, crashes, retries, and restarts without executing an unapproved operation. Do not rely on command-string matching alone for security: resolve paths and constrain actual execution privileges.

### 6.6 Bilingual interface and visual system

English is the default; Persian is selectable and persistent. Use a message catalog with stable IDs, interpolation, pluralization, localized date/number formatting as needed, and missing-translation detection. Set document `lang` and `dir` correctly; technical identifiers, paths, commands, and diffs remain LTR with deliberate bidirectional isolation. Test both languages for overflow, keyboard order, focus states, and screen-reader labels.

The approved spatial design shows Hermes as coordinator, agents as agents, tools as tools, projects as projects, containers as execution boundaries, and workflows as links or sequences—not interchangeable node types. A 2D shell always provides mission lists, approval queue, technical diffs, timeline, and fallback graph/list view. The 3D layer is progressive enhancement and must never be the only path to an approval. Avoid flashing; honor reduced-motion settings and provide a lightweight mode. Use connection, execution, and control statuses independently; do not encode status solely by color.

> **Approved architectural direction; frontend migration not yet scheduled (2026-09-26):**
> - The target frontend for the product is React + TypeScript.
> - The approved futuristic, spatial dashboard may use React Three Fiber / Three.js as an optional visualization layer.
> - Essential functions—including approvals, diffs, event history, project/tool settings, and language selection—must remain usable in a clear 2D interface without 3D.
> - English is the default UI language; Persian is selectable and uses RTL. Technical content such as commands, file paths, and diffs must remain readable in LTR.
> - Keep the existing Python control service as the backend baseline. Do not rewrite it in Rust or Mojo based only on an expectation of higher speed.
> - Rust may be considered later for a narrowly scoped, measured performance bottleneck, with a benchmark and migration plan. Mojo is not selected for the product's core at this stage.
> - UI responsiveness, event latency, and correctness of approval enforcement should be measured separately before proposing performance-related changes.
> - **Phase 1 scope boundary:** Continue the already agreed Phase 1 task in the existing UI; do not replace it with a React migration or alter API contracts merely to adopt React.

## 7. Roadmap: one item at a time

Each phase below identifies the **next single focus**. Do not parallelize phases merely to accelerate appearance. A phase may be broken into smaller one-item tasks. The next phase begins only when the owner's acceptance gate has passed.

### Phase 0 — Establish the safe local baseline

**Objective:** Know what is already present and preserve a way back.  
**Scope:** Read-only inspection of local working tree, repo remotes/visibility, file tree, configuration, baseline tests, application startup, and sensitive-data exposure risks. Do not change WordPress or existing containers.  
**Deliverable:** A baseline report with exact environment, commands run, pass/fail counts, unresolved risks, and recovery steps.  
**Gate:** Owner confirms a repeatable launch and test procedure, or explicitly records blockers. No claims of passing tests based only on commit text.

### Phase 1 — Bilingual foundation in the existing UI

**Objective:** English-default UI with selectable Persian/RTL.  
**Scope:** Extract visible strings, add translation catalogs and persistence, set `lang`/`dir`, preserve LTR technical text, add focused tests. No redesign or 3D work.  
**Gate:** Owner can switch languages locally; approvals and technical values remain readable; existing API behavior and tests remain intact.

### Phase 2 — Project registry, read-only

**Objective:** Register and inspect a real project through UI without touching its files.  
**Scope:** Select execution environment, choose/enter project root, validate paths and ownership, show summary and existing services without mutating them. Use `/home/mehdi/workspace/wp-bioscentiran` only as the owner's test case.  
**Gate:** A project is added and viewed; invalid or escaped paths are rejected; WordPress/MariaDB still work unchanged.

### Phase 3 — Tool discovery and explicit registration

**Objective:** Discover candidate tools in the chosen environment and add one with consent.  
**Scope:** PATH/approved-location search and safe probes for DSH/Docker/Git as applicable; Windows Hermes discovery is a separate connector investigation. No installs, shell-wide scanning, or automatic grants.  
**Gate:** UI accurately reports discovered, verified, unavailable, and registered states; no execution authority arises from discovery alone.

### Phase 4 — Honest event ingestion and operational timeline

**Objective:** Observe one real workflow end-to-end.  
**Scope:** Choose a supported integration surface based on the owner's installed Hermes/DSH versions; ingest source-tagged events, handle reconnect/retry, persist bounded sanitized evidence. Start with observation only.  
**Gate:** A locally executed test mission generates traceable, correlated events; missing visibility is labeled explicitly; no fabricated sub-agent activity.

### Phase 5 — A single real approval gate

**Objective:** Intercept one narrowly specified sensitive action before execution.  
**Scope:** Pick a demonstrably interceptable action in one runtime (for example, a controlled test file write); implement request, pending, deny, approve, expiration, and revalidation. Do not claim global protection across Hermes and DSH.  
**Gate:** Repeated tests prove no execution before approval, no execution after denial/expiry, and no reuse or altered-action approval. Validate behavior on crash/restart and disconnected UI.

### Phase 6 — Per-project runner and constrained authority

**Objective:** Give one project an isolated runner without disturbing its existing services.  
**Scope:** Review exact Docker mounts and permissions; use a disposable test project first; then enable selected low-risk actions for the WordPress project. Protect secrets, disallow Docker socket exposure to agents, and keep a manual rollback.  
**Gate:** Runner cannot see unrelated host paths; permitted workspace operations work; sensitive files and WordPress/MariaDB data remain intact. Record limitations of the isolation boundary.

### Phase 7 — Reliable everyday-use loop

**Objective:** Use Agent OS during real work for an agreed trial period.  
**Scope:** Handle restart recovery, backups, event retention, errors, duplicate events, jobs stuck pending, notifications, and clearly scoped emergency stop. Fix observed defects one at a time.  
**Gate:** Owner can complete a real mission, review evidence, make a sensitive decision, restart safely, and restore from a tested backup. Report actual daily-use failures.

### Phase 8 — Product UI shell and spatial visualization

**Objective:** Realize the approved mission-control design without compromising clarity.  
**Scope:** Build the readable 2D shell and responsive operational view first; then add the animated 3D workflow layer from actual event data. Support English/Persian, keyboard control, reduced motion, and 2D fallback.  
**Gate:** User can finish the same mission and approval tasks with 3D disabled; performance is acceptable on the owner's hardware; nothing in the visual graph implies unobserved behavior.

### Phase 9 — User-defined workflows and adapters

**Objective:** Enable website design, SEO content, and multilingual software-development workflows without hard-coding the owner's stack.  
**Scope:** Reusable project templates, tool capability profiles, connector contracts, permissions per workflow, and dry-run/previews. Add new adapters based on real demand, one at a time.  
**Gate:** At least one workflow in each target category works through the same core controls and can be configured through UI; no template silently receives high-risk privileges.

### Phase 10 — Private product hardening and release decision

**Objective:** Decide whether a public release is justified.  
**Scope:** Threat model and tests, installer/onboarding, CI, migration/backup, accessibility review, performance, documentation, license choice, dependency review, sanitized samples, and secret/history review.  
**Gate:** Owner signs off on a release checklist and decides exactly which repository/history/artifacts become public. No automatic open-source publication.

## 8. Acceptance and quality matrix

For every change capture: task ID, proposed behavior, exact files/systems in scope, prohibited operations, test command and output, manual reproduction steps, rollback, and owner decision. At minimum, test these failure cases before depending on enforcement:

- Unknown project root, symlink/path traversal, and a path outside the approved workspace.
- Sensitive file edit and delete, including indirect modification through a tool.
- Secret visible in stdout, event payload, screenshot, diff, or a staged Git change.
- Agent/tool goes offline after approval request; approval expires; action parameters change.
- Service restarts mid-run, duplicate events arrive, approvals are replayed, and a job times out.
- English and Persian layout, mixed-script paths/diffs, missing translations, keyboard-only usage.
- Docker runner can reach an unauthorized host path, socket, network endpoint, or another project's data.
- An integration does not expose enough events to render a claimed state.

Test results must identify *what actually ran on the owner's system*. Repository edits performed remotely do not establish that a Windows Desktop, WSL, Docker, or WordPress integration passed locally.

## 9. Immediate task for Hermes — Phase 0 only

Hermes should **not** begin coding the dashboard from this document. First execute only this read-only baseline task, after the owner approves running the listed diagnostics locally:

1. Identify the local Agent OS working directory and confirm the current Git branch, remote URL(s), repository visibility, and uncommitted changes; redact private URLs/identifiers where needed.
2. Enumerate the existing code, tests, and documented launch/test commands. Inspect the UI entry point and implementation boundaries.
3. Run the project's documented non-destructive test suite and local launch/smoke check in the owner's WSL environment; never run destructive end-to-end checks against the live WordPress project.
4. Report actual commands, outputs, failures, dependencies, and whether secrets or local state might be tracked. Do not print secret values in the report.
5. Propose *one* next bounded task, expected files, acceptance criteria, and rollback; wait for explicit human approval before edits.

### Copy-ready coordinator instruction

> You are coordinating Agent OS development for its human owner. Treat this master plan as product intent, not blanket authorization. Work on only Phase 0 now. Investigate the existing local repository read-only, identify the environment and safe test commands, run only tests that cannot mutate the owner's WordPress project or external systems, and produce an evidence-based baseline report. Do not create a repository, push, commit, modify configuration, install software, alter containers, or expose secrets without a separate explicit approval showing exact targets and changes. Do not start Phase 1 until the owner accepts the Phase 0 report. Delegate to DSH only a narrow, owner-approved task. If an integration capability is unverified, mark it unknown rather than assuming it works.

## 10. Open decisions for later, not blockers for Phase 0

- Exact private repository strategy and whether old public history should be imported or only a vetted source snapshot.
- Whether the owner wants a standalone local app, a browser-served local UI, or both.
- Precise installed Hermes/DSH versions and verified event/interception capabilities.
- Runner image and boundaries for PHP/Node/Python projects; Docker Desktop networking and cross-boundary access.
- Specific sensitive-file patterns, network allowlists, audit retention, backup schedule, and acceptable residual risks.
- [Resolved: React + TypeScript target; R3F/Three.js optional 3D layer; Python backend preserved] Scheduling of frontend migration post-Phase 1.

**Success condition:** Agent OS earns the owner's daily trust through honest visibility and enforceable boundaries; its futuristic presentation makes that dependable experience delightful rather than hiding its limitations.
