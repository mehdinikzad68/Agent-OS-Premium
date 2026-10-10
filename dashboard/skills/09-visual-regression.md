# Skill 09: Visual Baseline and Regression Check

## Goal
Protect the visual identity of the dashboard, especially the central holographic coordinator, while the code changes.

## Baseline
1. Before any change, capture screenshots at fixed viewports, for example 1440x900 and 390x844, in LTR (English) and RTL (Persian).
2. Stabilize randomness and time where possible: use the seed option or a frozen time parameter if the renderer supports it. If it does not, record that the comparison is approximate.
3. Store baselines under a dedicated folder, not inside the source.
4. Record the commit or working tree state used for the baseline.

## Comparison
1. Capture the same views after changes.
2. Compare the hologram region and the default composition.
3. Report differences as: none, minor (describe), or major (describe).
4. Do not claim pixel-perfect equivalence unless a pixel diff tool was run and reported.

## Rules
- Do not change colors, fonts, glow values, or head geometry while doing a feature task.
- If a change is intentional, list it explicitly in the report and wait for approval.
- Animation-driven differences must be described, not hidden.
- Do not use screenshots as evidence of live data. They show visuals only.

## Acceptance
- Hologram region recognizable and unchanged in intended design.
- Default layout resembles baseline.
- Persian RTL layout does not break labels or panels.
- Reduced-motion mode shows reduced animation without layout change.

## Report
- Viewports tested.
- Baseline reference location (relative path).
- Comparison result per viewport.
- Test status: PASS / FAIL / NOT RUN.
