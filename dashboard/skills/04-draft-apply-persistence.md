# Skill 04: Modes, Draft, Apply, Undo, and Persistence

## Goal
Add Observe and Edit modes, a draft change set, a review step, simulated apply through a mock adapter, undo/redo, and validated local persistence.

## Modes
- Observe: inspect only. No topology or position changes.
- Edit: changes go into the draft. Positions and geometry may change as view state.

## Draft rules
- Draft contains operational changes: add or remove registration, add or remove connection, change permission, change connection state.
- View changes (position, curvature, grouping, visibility) are saved as view state. They are not operational changes.
- The status bar shows the count of unapplied operational changes, for example "3 unapplied changes", with Review, Apply changes, and Discard.
- Review shows: added entities, removed registrations, added connections, removed connections, changed permissions, layout-only changes.

## Apply rules
- Apply is simulated through the mock adapter. The UI must label it "Simulated application".
- The adapter returns a per-operation result: accepted, rejected, or partial.
- Never show full success if any operation was rejected.
- After a rejected operation, the draft keeps the rejected item with its reason.

## Undo and redo
- Undo and redo apply to draft and view changes only.
- Undo must not be described as reverting a completed backend operation.
- Undo history is bounded (define the limit, for example 100 steps).

## Persistence
- Store non-secret view and workspace configuration in localStorage behind a storage interface, so a future service can replace it.
- Every stored record has `schemaVersion`.
- Validate on load. On malformed data: keep defaults for the affected section, log a readable error, and do not crash.
- Export produces JSON without credentials or private paths.
- Import shows a preview with validation errors before applying.
- Reset to defaults affects only the chosen section (layout, navigation, or all).
- Document that browser storage is local, not multi-user persistence.

## Steps
1. Define schemas and validators for view state and workspace config.
2. Implement the storage interface and the localStorage implementation.
3. Implement the draft store with add, remove, and commit-to-draft functions.
4. Implement undo/redo as a reducer with bounded history.
5. Implement Review, Apply (mock), and Discard.
6. Implement export and import with preview.

## Acceptance tests
- Draft create, apply, discard.
- Undo and redo restore draft state exactly.
- Mock apply with one rejected operation shows partial result, not success.
- Reload restores non-secret layout.
- Malformed import is rejected with readable errors and no crash.
- Exported JSON contains no token-like strings (test with a pattern check).
