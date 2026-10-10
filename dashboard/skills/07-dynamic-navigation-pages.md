# Skill 07: Dynamic Navigation and Declarative Pages

## Goal
Generate navigation and standard pages from validated declarative configuration instead of fixed JSX arrays.

## Manifest rules
- Versioned: every manifest has `schemaVersion`.
- Navigation items have: stable id, localized label, icon identifier from an allowlist, order, visibility, route, page renderer id, capability requirements, permission requirements.
- Renderer identifiers map to a registry of known components. Unknown renderer names produce a safe, readable error panel.
- No executable code in manifests. No `eval`, no `new Function`, no dynamic script loading.

## Initial renderers
- resource-table
- resource-detail
- schema-form
- timeline
- command-canvas

## Customization UI
- Add a navigation entry.
- Reorder entries.
- Show or hide entries.
- Create a page from a supported template.
All changes are draft changes and follow skill 04 rules for persistence and validation.

## Rules
- Hiding a UI action is not authorization. Document that the backend must enforce permissions.
- Capability gating: if a capability is not supported, the entry is shown as unavailable with an explanation, or hidden, per the manifest setting.
- Do not add navigation items with routes that cannot be resolved.

## Steps
1. Define the manifest schema and validator.
2. Build the renderer registry.
3. Build the navigation generator from validated config.
4. Build the page router from validated config.
5. Add the customization UI using draft actions.

## Acceptance tests
- Add a navigation item and a standard page without editing the App component.
- Unknown renderer shows a safe error, not a crash.
- Malformed manifest is rejected with readable errors.
- Hidden item is not in navigation but its data is not deleted.
- Capability unsupported shows explanation.
