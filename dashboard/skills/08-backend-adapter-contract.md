# Skill 08: Backend Adapter Contract

## Goal
Define a provider-neutral adapter interface, implement a functional mock adapter, and document how an Agent OS adapter would fit. Do not implement real endpoints unless they are verified and documented.

## Interface (minimum)
- getCapabilities(): returns supported capabilities.
- listResources(kind, query): paged list for registered entities.
- getResource(kind, id).
- validateChanges(changeSet): per-operation validation result.
- applyChanges(changeSet): per-operation result with accepted, rejected, or partial status.
- getExecutionSnapshot(scope).
- subscribeEvents(scope, handler): returns unsubscribe.
- requestAction(action): returns receipt with requested status.
- queryMemory(request): returns result or error.

## Capability model
Keep four facts separate:
- Supported: the provider implements it.
- Authorized: the current user may use it.
- Available: the service is reachable now.
- Configured: required settings exist.

## Rules
- The UI never builds URLs. Only adapters do.
- The UI never reads secrets. Adapters receive credentials through a secure boundary, not from view state.
- Unsupported actions are visibly unavailable with an explanation.
- Cancellation has two states: cancellation requested, cancellation confirmed. Never collapse them.
- Do not claim pause, descendant cancellation, or retry unless the capability is declared.
- Retry creates a new run. It never rewrites the previous run.
- Failures must be returned as typed errors, not thrown into the renderer.
- Timeouts, abort on unmount, and stale-response protection are required for any fetch.

## Mock adapter
- Deterministic data.
- Labeled MOCK in responses.
- Supports simulated apply with partial failure for testing.
- Supports scripted event streams for skill 06 scenarios.

## Agent OS adapter (future)
Before writing this adapter, the agent must:
1. Inspect the Agent OS backend repository read-only.
2. List actual endpoints, methods, auth requirements, and response shapes with file references.
3. Map each endpoint to an adapter method or mark it unsupported.
4. Stop and request approval before implementation.

Do not invent endpoints.

## Acceptance tests
- Renderer code contains no URL strings (grep check).
- Mock adapter passes contract tests.
- Partial apply result displays partial status.
- Unsupported capability disables the related control and shows explanation.
- A second mock adapter with different capabilities changes the UI gating without code changes in components.
