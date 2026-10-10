// Shared-memory access policy model (skill 05). Pure.
//
// Access policy is SEPARATE from connection state:
//   authorized  this policy grants (agentId, scope)
//   available   a configured, enabled memory-read connection
//   retrieval   an actual query event
//
// Subagents do NOT inherit parent access: grants are
// per agent id and per scope.

export const POLICY_SCHEMA_VERSION = 1;

/** Build a policy from grants. Invalid grants are
 *  dropped (graceful, never throws). */
export function createPolicy(grants = []) {
  const clean = (grants || []).filter(
    (g) =>
      g &&
      typeof g.agentId === "string" &&
      g.agentId.length > 0 &&
      typeof g.scope === "string" &&
      g.scope.length > 0 &&
      g.access === "read"
  );
  return { schemaVersion: POLICY_SCHEMA_VERSION, grants: clean };
}

/** Does the policy grant `agentId` read access to `scope`? */
export function hasReadAccess(policy, agentId, scope) {
  return (policy?.grants || []).some(
    (g) => g.agentId === agentId && g.scope === scope
  );
}

/** All scopes an agent may read. */
export function scopesForAgent(policy, agentId) {
  return (policy?.grants || [])
    .filter((g) => g.agentId === agentId)
    .map((g) => g.scope);
}

/** All agents with a grant (optionally for one scope). */
export function agentsWithAccess(policy, scope = null) {
  return (policy?.grants || [])
    .filter((g) => scope == null || g.scope === scope)
    .map((g) => g.agentId);
}
