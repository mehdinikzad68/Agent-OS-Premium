export interface SimulatedAgentNode {
  id: string;
  name: string;
  role: string;
  command: string;
  status: "active" | "awaiting" | "offline";
  truthState: "observed-only" | "unknown";
  tokens: string;
  loadPercent: number;
}

export interface SimulatedApproval {
  id: string;
  tier: "T2" | "T3";
  title: string;
  requester: string;
  targetResource: string;
  diffSummary: string;
}

export interface SimulatedFlightEvent {
  seq: number;
  time: string;
  kind: string;
  source: string;
  summary: string;
}

export interface DashboardFixtureData {
  projectName: string;
  missionTitle: string;
  environment: string;
  nodes: SimulatedAgentNode[];
  approvals: SimulatedApproval[];
  events: SimulatedFlightEvent[];
}

export const DASHBOARD_FIXTURE: DashboardFixtureData = {
  projectName: "simulated-demo-project",
  missionTitle: "M-101: Scaffold Verification Architecture",
  environment: "Simulated Testbed (Offline)",
  nodes: [
    {
      id: "hermes-core",
      name: "Hermes Core",
      role: "Central Orchestrator",
      command: "ANALYZE EXECUTION DAG",
      status: "offline",
      truthState: "observed-only",
      tokens: "0",
      loadPercent: 0
    },
    {
      id: "dsh-worker",
      name: "DSH Harness",
      role: "Subprocess Worker",
      command: "IDLE / DISCONNECTED",
      status: "offline",
      truthState: "unknown",
      tokens: "0",
      loadPercent: 0
    },
    {
      id: "docker-adapter",
      name: "Container Sandbox",
      role: "Isolated Runtime",
      command: "CONTAINER NOT ACTIVE",
      status: "offline",
      truthState: "unknown",
      tokens: "0",
      loadPercent: 0
    },
    {
      id: "seo-agent",
      name: "SEO Crawler",
      role: "External Analyzer",
      command: "STANDBY",
      status: "offline",
      truthState: "unknown",
      tokens: "0",
      loadPercent: 0
    },
    {
      id: "wordpress-bridge",
      name: "WordPress Bridge",
      role: "Target Site Bridge",
      command: "NOT CONFIGURED",
      status: "offline",
      truthState: "unknown",
      tokens: "0",
      loadPercent: 0
    },
    {
      id: "antigravity-ide",
      name: "Antigravity IDE",
      role: "Host Pairing Agent",
      command: "DISCONNECTED",
      status: "offline",
      truthState: "unknown",
      tokens: "0",
      loadPercent: 0
    }
  ],
  approvals: [
    {
      id: "SIM-APP-001",
      tier: "T3",
      title: "Rotate Security Boundary Keys",
      requester: "simulated-operator",
      targetResource: "/workspace/config/security.json",
      diffSummary: "- \"enforce_auth\": false\n+ \"enforce_auth\": true"
    },
    {
      id: "SIM-APP-002",
      tier: "T2",
      title: "Update Static Probe Allowlist",
      requester: "simulated-auditor",
      targetResource: "/workspace/policies/allowlist.txt",
      diffSummary: "+ probe: read-only-filesystem"
    }
  ],
  events: [
    {
      seq: 1,
      time: "12:00:00",
      kind: "system.boot",
      source: "local-shell",
      summary: "Dashboard scaffold initialized in offline simulated mode"
    },
    {
      seq: 2,
      time: "12:00:05",
      kind: "policy.verify",
      source: "static-harness",
      summary: "Strict zero-network assertion verified"
    },
    {
      seq: 3,
      time: "12:00:10",
      kind: "fixture.load",
      source: "memory-store",
      summary: "Simulated fixture nodes registered with truth boundaries"
    }
  ]
};