# Skill 02: Canvas Graph Model and Node Layout

## Goal
Introduce a graph model and draggable peripheral nodes while keeping the central coordinator fixed and the default layout visually close to the original.

## Scope
In scope:
- Graph model for registered nodes (orchestrator, agent, tool, memory).
- Node positions, lock state, visibility, and grouping as view state.
- Node selection and dragging.
- Automatic placement for new nodes that does not move existing manual positions.
- Reset-layout action, separate from system reset.
- World-to-screen and screen-to-world coordinate helpers.

Out of scope:
- Fiber editing (skill 03).
- Draft and apply logic (skill 04).
- Changes to head geometry, backdrop, colors, or fonts.

## Rules
- The coordinator is identified by a configurable role, not a hardcoded id in the generic model. Preserve an example default if the source has one.
- Keep registered entities, view configuration, and runtime state in separate data structures.
- Node positions are stored in view state, never in the registered entity record.
- The renderer receives a read-only snapshot. It must not contain backend URLs or provider logic.
- Do not route per-frame animation through React state. Keep the animation loop reading from a ref.
- Use stable string ids. Never use array index as identity.

## Steps
1. Define types or JSDoc typedefs for: RegisteredNode, ViewNodePosition, ViewState.
2. Write a pure function `layoutDefault(nodes, viewport)` that reproduces the original arrangement for the default set.
3. Write `placeNewNode(existingPositions, newNode, viewport)` that never moves existing positions.
4. Implement drag with pointer events and pointer capture. Clamp to the canvas bounds.
5. Implement lock: locked nodes cannot be dragged.
6. Implement `resetLayout()` that only resets view positions.
7. Add unit tests for layout, placement stability, and coordinate round-trip.

## Acceptance
- Dragging a peripheral node does not move the coordinator.
- Adding a node leaves all other manual positions unchanged.
- Reset layout does not change registered entities.
- Default viewport screenshot is visually close to baseline (see skill 09).
- Hit targets match drawn nodes after window resize.

## Report
- Tests: PASS / FAIL / NOT RUN with commands.
- Any change to the default visual layout, with a screenshot comparison result or NOT RUN.
