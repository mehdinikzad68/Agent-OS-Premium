# Skill 06: Runtime Executions, Subagent Clusters, and Timeline

## Goal
Show parallel and nested runtime executions around a registered parent agent, with a timeline, using a provider-neutral event contract.

## Core distinctions
- Registered parent agent: a stable entity.
- Mission: a unit of work.
- Run: one execution with its own runId.
- Child run: created by a parent run.
- Nested child run: created by a child run.
Never identify a run by agent name alone.

## Event contract
Each event includes: eventId, sequence, occurredAt, receivedAt, missionId, runId, parentRunId, agentId, type, assignedTask (optional), reportedActivity (optional), waitingReason (optional), artifactRefs (optional), error (optional).

Event types: run.created, run.started, run.activity, run.waiting, run.completed, run.failed, run.cancelled.

## Reducer rules
- Deduplicate by eventId.
- Order by occurredAt and sequence within a run.
- Never overwrite a newer state with an older event.
- Accept late events and place them by timestamp.
- Handle a snapshot followed by events after reconnection.
- Missing telemetry does not change execution state. Track freshness separately.
- Keep the store testable without React.

## States
- Execution state: queued, running, waiting, succeeded, failed, cancelled.
- Waiting reason: approval, tool, dependency, user input.
- Telemetry freshness: fresh, stale, unavailable.
- Show "2 of 3 runs finished" separately from "2 of 3 runs succeeded".

## Rules
- Do not show percentage progress unless explicit measurable progress data exists.
- Do not infer current work from the assigned task.
- Do not display hidden reasoning. Show only reported activity.
- Parent-child edges are read-only and must not be draggable.
- If a provider has no subagent telemetry, show "Subagent telemetry unavailable". Never show zero subagents as established fact.

## Clusters
- Collapsed: "3 active subagents", "1 waiting".
- Expanded: smaller nodes around the parent with role, short task, state, elapsed time.
- Controls: expand, collapse, active-only filter, mission filter, nested inspection.
- Runtime nodes must be visually subordinate to the central hologram.

## Timeline
- One row per run, nested by parent.
- Shows active intervals, waiting intervals, and terminal markers.
- Synchronized selection with canvas and Inspector.
- Replay is observational only. It must not trigger tools or config changes.

## Mock scenarios (required)
1. Parent spawns three children in parallel.
2. One child succeeds.
3. One child waits on approval.
4. One child fails.
5. Parent aggregates results.
6. A nested child.
7. Memory retrieval and return.
8. Stale telemetry.
9. Duplicate and out-of-order events.
10. Provider without subagent telemetry.

Mock events must be labeled MOCK and kept separate from live data.

## Acceptance tests
- Reducer tests for duplicate, out-of-order, and late events.
- Parent-child association by runId and parentRunId.
- Expanded cluster shows correct counts from the reducer.
- Unavailable telemetry shows the explicit message.
- Timeline shows overlap for concurrent runs.
