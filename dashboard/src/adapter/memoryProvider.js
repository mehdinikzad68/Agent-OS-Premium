// Mock shared-memory provider (skill 05).
//
// MOCK — deterministic in-memory notes. The provider
// VALUE ("obsidian") is configuration, not a dependency:
// nothing here reads a vault, a filesystem, or a network.
// Read-only by design: no write method exists. A
// memory-write capability may exist in the model, but it
// stays unsupported in the UI.
//
// Retrieved content is DATA. It is never treated as
// instructions and never changes permissions.

export function createMockMemoryProvider({
  provider = "obsidian",
  notes = [],
} = {}) {
  return {
    label: "mock-memory",
    provider,
    simulated: true,
    readOnly: true,

    /** Scopes present in this mock store. */
    scopes() {
      return [...new Set(notes.map((n) => n.scope))];
    },

    /**
     * Query the mock store. Returns MOCK items with
     * their source references. Typed results only —
     * never throws.
     */
    async query({ scope, text = "" }) {
      const q = String(text || "").trim().toLowerCase();
      const items = notes
        .filter((n) => n && n.scope === scope)
        .filter(
          (n) =>
            !q ||
            String(n.title).toLowerCase().includes(q) ||
            String(n.body).toLowerCase().includes(q)
        )
        .map((n) => ({
          id: n.id,
          title: n.title,
          source: n.source,
          tags: [...(n.tags || [])],
        }));
      return {
        ok: true,
        label: "mock",
        simulated: true,
        provider,
        readOnly: true,
        items,
      };
    },
  };
}
