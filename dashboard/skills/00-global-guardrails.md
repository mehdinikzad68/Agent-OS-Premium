# Skill 00: Global Guardrails

## Applies to
Every task on the dashboard source.

## Must do
- Work only inside the dashboard frontend project. Verify the project root first.
- Run a read-only inspection (see skill 01) before any edit, unless the task is already scoped to specific files that were approved.
- Report `git status` before and after changes when Git is available.
- Keep the holographic coordinator and the existing visual identity unchanged unless the task explicitly targets them.
- Label every simulated behavior as MOCK in code comments, UI text, and the README.
- Report every test as PASS, FAIL, or NOT RUN. Never claim a test passed without output.
- Stop and report when a file path, dependency, API, or capability is assumed rather than verified.

## Must not do
- Modify external backend code.
- Read or write a real Obsidian vault or any local filesystem path outside the project.
- Execute real system commands from the dashboard.
- Embed, print, or store credentials, tokens, or private paths.
- Add a remote plugin marketplace or execute code from manifests, `eval`, or `new Function`.
- Run `git commit`, `git push`, `git reset`, `git clean`, `git stash`, or change branches.
- Delete or overwrite unrelated user changes.
- Add a dependency without listing it, justifying it, and waiting for approval.
- Claim real integration, pixel-perfect equivalence, or production readiness without evidence.

## Gates
Stop and wait for human approval at:
1. After the inspection report and before any edit.
2. After the change plan and before applying it.
3. After tests, before any commit proposal.

## Required report footer
- Files added (relative paths).
- Files changed (relative paths).
- Dependencies added (name, version, reason).
- Test results (PASS / FAIL / NOT RUN, with command).
- Mock versus real behavior.
- Known limitations.
- Open questions.
