# Mission Control UI Design Reference

This directory contains visual reference assets for the Agent-OS Mission Control dashboard.

## Files

- `UI-agent-Ltl.png` — English/LTR reference screenshot, 1916×985.
  The filename uses `Ltl` for historical reasons; it represents the LTR design.
- `UI-agent-RTL.png` — Persian/RTL reference screenshot, 1909×984.
- `agent-os-neural-command-robot.html` — static visual prototype of the Neural Command design.

## Status

These files are **design references only**.

They are not the production dashboard implementation and must not be treated as evidence of live Agent-OS integrations, approval enforcement, tool execution, or real-time agent state.

The current production UI implementation remains:

```text
control-service/agent_os/web/index.html
```

## Rendering approach

The prototype uses a Canvas 2D scene for the Neural Command visualization. It does not use Three.js or WebGL.

## Network and privacy

- The prototype imports fonts from Google Fonts, so it is not a fully offline-first artifact.
- It contains no API credentials, tokens, bearer values, private keys, or real passwords.
- Credential-like strings shown in the visual diff are redacted placeholders.

## Usage

Open `agent-os-neural-command-robot.html` in a browser to inspect the visual reference. No backend, server, build step, or API access is required.
