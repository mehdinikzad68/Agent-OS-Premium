# Skill 03: Fiber Interaction and Connection Editing

## Goal
Make luminous fibers interactive: change curvature (view only) and reconnect endpoints (draft configuration), without changing the visual style of the bundle.

## Model rules
- One fiber bundle equals one logical configured connection.
- Ports have stable ids and a kind: control, tool-access, memory-read, memory-write.
- Compatibility is defined by an explicit rule table, not by ad hoc checks in the renderer.
- Duplicate connections are rejected by a rule: same source port, same target port, same type.
- Cycles are allowed or rejected per connection type. Define the table; do not ban all cycles silently.
- A connection never grants permissions by existing. Permissions are separate records.

## Interaction rules
- Midpoint or control handle drag: updates view geometry only.
- Endpoint drag: creates a draft reconnect operation.
- Dropping on empty space cancels the reconnect. It must not delete the connection.
- While reconnecting, the previous valid connection remains until the draft operation is accepted by validation.
- Escape cancels the active operation.
- `pointercancel` and `lostpointercapture` cancel the operation.
- Use `setPointerCapture` during drag and release it on end or cancel.
- Hit area must be wider than the visible strand, for example 12 to 16 px, without changing the visual width.
- While dragging a fiber, node dragging is disabled.
- In Observe mode, no topology interaction is enabled. Only selection and inspection.

## Non-drag alternative (mandatory)
Provide a keyboard and click flow:
Select source port, choose "Connect to", select target port, choose connection type, confirm.
- Every control must have an accessible name.
- Focus must be visible.
- Status must be announced in text, not only by color.

## Steps
1. Implement the compatibility and duplicate rules as pure functions with tests.
2. Implement geometry: sample the Bezier path, provide `nearestPointOnPath(point)`.
3. Implement curvature handle and store control points in view state.
4. Implement endpoint reconnect state machine: idle, hover, dragging, previewing, validated, cancelled.
5. Implement visual feedback: valid target highlight, invalid target feedback, snap indicator.
6. Implement the non-drag flow.
7. Implement explicit Disconnect action with confirmation in Edit mode.

## Acceptance tests
- Reconnect to a valid target creates a draft change.
- Incompatible target shows invalid feedback and does not change the draft.
- Drop on empty space keeps the original connection.
- Escape during drag restores the original geometry.
- Changing curvature does not create a draft topology change.
- Creating a connection without dragging works end to end.

## Report
- State machine diagram or table.
- Test results PASS / FAIL / NOT RUN.
