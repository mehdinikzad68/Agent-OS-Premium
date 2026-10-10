// Access policy model tests (skill 05).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createPolicy,
  hasReadAccess,
  scopesForAgent,
  agentsWithAccess,
} from "../src/model/memory.js";

test("createPolicy keeps valid grants and drops invalid ones", () => {
  const policy = createPolicy([
    { agentId: "dsh", scope: "obsidian/notes", access: "read" },
    { agentId: "", scope: "x", access: "read" },
    { agentId: "seo", scope: "x", access: "write" },
    null,
    "nope",
  ]);
  assert.deepEqual(policy.grants, [
    { agentId: "dsh", scope: "obsidian/notes", access: "read" },
  ]);
  assert.equal(policy.schemaVersion, 1);
});

test("hasReadAccess is per agent AND per scope", () => {
  const policy = createPolicy([
    { agentId: "dsh", scope: "obsidian/notes", access: "read" },
  ]);
  assert.equal(hasReadAccess(policy, "dsh", "obsidian/notes"), true);
  assert.equal(hasReadAccess(policy, "dsh", "obsidian/ops"), false);
  assert.equal(hasReadAccess(policy, "seo", "obsidian/notes"), false);
  assert.equal(hasReadAccess(null, "dsh", "obsidian/notes"), false);
});

test("subagents do not inherit parent access", () => {
  const policy = createPolicy([
    { agentId: "parent-agent", scope: "vault/secret", access: "read" },
  ]);
  assert.equal(hasReadAccess(policy, "parent-agent", "vault/secret"), true);
  assert.equal(
    hasReadAccess(policy, "child-of-parent-agent", "vault/secret"),
    false
  );
});

test("scopesForAgent and agentsWithAccess", () => {
  const policy = createPolicy([
    { agentId: "dsh", scope: "a", access: "read" },
    { agentId: "dsh", scope: "b", access: "read" },
    { agentId: "seo", scope: "a", access: "read" },
  ]);
  assert.deepEqual(scopesForAgent(policy, "dsh"), ["a", "b"]);
  assert.deepEqual(scopesForAgent(policy, "ghost"), []);
  assert.deepEqual(agentsWithAccess(policy), ["dsh", "dsh", "seo"]);
  assert.deepEqual(agentsWithAccess(policy, "b"), ["dsh"]);
  assert.deepEqual(agentsWithAccess(null), []);
});
