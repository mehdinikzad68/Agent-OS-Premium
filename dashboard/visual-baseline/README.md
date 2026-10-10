# Visual Baselines (Skill 09)

Capture date: 2026-10-09. Project is **not a git repo** — worktree state is
recorded by test count + build output instead of a commit hash:

- `npm test`: 162/162 passing at capture time
- `npm run build`: 1779 modules, CSS 24.66 kB, JS ~315 kB
- 39 source files under `src/`, no uncommitted changes pending

## Environment

- Browser: desktop Chromium via OpenCode bridge, DPR **1.25**
- Base viewport: 980 x 766 (no viewport-resize tool exists; fixed viewports
  were emulated with a same-origin fullscreen iframe, see below)
- State: seed workspace (reset via WorkspaceTools), FA default language
- Reduced motion: `prefers-reduced-motion` is **not emulated** (no tool);
  respected in code at `src/scene/NeuralScene.jsx:230`

## Files

| File | Viewport | Language | Notes |
| --- | --- | --- | --- |
| `before/01-fa-home-980x766-before.png` | 980 x 766 (real window) | FA/RTL | |
| `before/02-en-home-980x766-before.png` | 980 x 766 (real window) | EN/LTR | |
| `before/03-fa-1440x900-before.png` | 1440 x 900 (iframe) | FA/RTL | |
| `before/04-fa-390x844-before.png` | 390 x 844 (iframe) | FA/RTL | cropped to 488x1055 device px |
| `before/05-en-1440x900-before.png` | 1440 x 900 (iframe) | EN/LTR | |
| `before/06-en-390x844-before.png` | 390 x 844 (iframe) | EN/LTR | cropped to 488x1055 device px |
| `after/*` | same set | same | captured after self-hosted fonts |

## Method (fixed viewports)

1. Hide the outer app (`body > *:not(#vp-capture){display:none}`).
2. Inject a same-origin iframe sized to the target viewport; wait for
   `readyState === 'complete'`, canvas presence and `document.fonts.status
   === 'loaded'`.
3. `fullPage` screenshot, then crop (System.Drawing) when the capture is
   wider than the viewport (`scrollWidth` cannot go below the window width).

## Limitations (recorded per skill 09)

- Comparisons are **approximate**: no pixel-diff tool is used; the 2D
  hologram animation is time-dependent, so fiber positions differ between
  any two captures even without code changes.
- The harness image *preview* was observed to show stale frames during the
  session; all saved files were verified by PNG dimensions + pixel sampling
  (left/right mean luminance) instead of trusting previews.
