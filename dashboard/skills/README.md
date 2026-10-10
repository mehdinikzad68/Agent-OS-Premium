# Agent OS Dashboard: Skills Pack

Purpose: operational instructions for an AI coding agent that modifies the Neural Command dashboard React source.

## How to use
1. Always load `00-global-guardrails.md` first.
2. Load exactly one task skill (01 to 08) per run.
3. Provide the architecture prompt (the Opus prompt) alongside the skill as context.
4. Require the agent to stop at each gate listed in the skill and wait for approval.

## Skill index
| File | Scope |
|---|---|
| 00-global-guardrails.md | Rules that apply to every task |
| 01-source-inspection.md | Read-only inspection and implementation plan |
| 02-canvas-graph-model.md | Graph model, node movement, layout, view state |
| 03-fiber-interaction.md | Fiber geometry, reconnect, pointer rules, non-drag alternative |
| 04-draft-apply-persistence.md | Observe/Edit modes, draft, undo/redo, apply via mock, persistence |
| 05-shared-memory-mock.md | Shared memory node with mock provider |
| 06-subagent-clusters-timeline.md | Runtime executions, clusters, event reducer, timeline |
| 07-dynamic-navigation-pages.md | Manifest-driven navigation and standard pages |
| 08-backend-adapter-contract.md | Adapter interface, capabilities, mock adapter, future Agent OS adapter |
| 09-visual-regression.md | Baseline capture and visual verification |

## Global rule
If a task conflicts with a guardrail, the guardrail wins. The agent must report the conflict and stop.
