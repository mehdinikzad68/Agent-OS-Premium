# Skill 01: Source Inspection and Plan

## Goal
Understand the actual source before changing anything, and produce a plan that a human can approve.

## Inputs
- The dashboard React project directory (path provided by the user).
- The architecture prompt for the target product.

## Steps
1. Identify the project root: the folder containing `package.json` with the dashboard scripts. Do not assume names; list candidates and confirm.
2. Read `package.json`, the Vite config, the test setup, and the lockfile type.
3. Read the entry point and the top-level App component.
4. Map the source by responsibility:
   - Visual shell and layout.
   - Canvas renderer: head generation, backdrop, fiber geometry, animation loop.
   - Node and link data.
   - Localization strings.
   - Styles and design tokens.
   - Existing API client or connection provider, if any.
5. Find hardcoded values and list them with file path and line range:
   - Navigation items and routes.
   - Agent, tool, and memory records.
   - Coordinator identity and any fixed id such as a specific provider name used as a structural key.
   - Approval and history data.
   - Branding strings.
6. Check for existing tests and the commands to run them. Record the exact commands.
7. Record `git status` if Git is available. Do not change it.
8. Produce the report and the change plan.

## Output
- Inspection report: project root, file map, hardcoded-value list, existing tests, risks.
- Change plan: files to add, files to change, files that must not change, dependencies (if any), test plan.

## Gate
Stop after the report and plan. Do not edit files until the user approves.

## Failure conditions
Stop and report if:
- No `package.json` with the dashboard project is found.
- The entry point or the canvas renderer cannot be located.
- The plan requires editing files outside the project root.
