"""Integration test for the full workflow lifecycle through the API.

Tests the complete flow: create template -> execute -> verify mission/jobs.
"""

from __future__ import annotations

import json
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os.adapters.fake import FakeExecutor
from agent_os.api import AgentOSApi, register_executor, unregister_executor
from agent_os.models import ApprovalDecision, JobState, Principal
from agent_os.service import ControlService

T0 = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class WorkflowIntegrationTest(unittest.TestCase):
    """Full workflow lifecycle through the API."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)
        self.api = AgentOSApi(self.svc, token="secret")
        register_executor("fake-executor", FakeExecutor(behavior="success"))

    def tearDown(self):
        unregister_executor("fake-executor")
        self.svc.close()
        shutil.rmtree(TMP, ignore_errors=True)

    def _call(self, method, path, body=None):
        return self.api.handle(method, path, body)

    def test_full_workflow_lifecycle(self):
        """Create template -> execute -> verify mission + jobs exist."""
        # 1. Create a workflow template
        status, wf = self._call("POST", "/api/workflows", {
            "title": "Deploy Pipeline",
            "description": "Build, test, deploy",
            "default_executor": "fake-executor",
            "inputs_schema": {
                "type": "object",
                "properties": {
                    "target_path": {"type": "string"},
                    "environment": {"type": "string"},
                },
            },
            "nodes": [
                {
                    "id": "build",
                    "action_type": "execute_job",
                    "metadata": {
                        "command": ["echo", "building", "{{inputs.target_path}}"],
                        "actions": ["run_command"],
                        "workspace_paths": ["/tmp"],
                    },
                    "depends_on": [],
                },
                {
                    "id": "test",
                    "action_type": "execute_job",
                    "metadata": {
                        "command": ["echo", "testing"],
                        "actions": ["run_command"],
                        "workspace_paths": ["/tmp"],
                    },
                    "depends_on": ["build"],
                },
                {
                    "id": "deploy",
                    "action_type": "execute_job",
                    "metadata": {
                        "command": ["echo", "deploying", "{{inputs.environment}}"],
                        "actions": ["run_command"],
                        "workspace_paths": ["/tmp"],
                    },
                    "depends_on": ["test"],
                },
            ],
        })
        self.assertEqual(status, 201)
        self.assertEqual(wf["title"], "Deploy Pipeline")
        self.assertEqual(len(wf["nodes"]), 3)

        # 2. Execute the workflow
        status, execution = self._call("POST", f"/api/workflows/{wf['id']}/execute", {
            "inputs": {
                "target_path": "/home/mehdi/workspace/Agent-OS",
                "environment": "production",
            },
        })
        self.assertEqual(status, 200)
        self.assertEqual(execution["status"], "active")
        self.assertIn("mission_id", execution)

        # 3. Verify mission was created
        status, mission = self._call("GET", f"/api/missions/{execution['mission_id']}")
        self.assertEqual(status, 200)
        self.assertEqual(mission["state"], "active")

        # 4. Verify root job was proposed (build has no dependencies)
        status, jobs = self._call("GET", "/api/jobs")
        self.assertEqual(status, 200)
        build_jobs = [j for j in jobs["jobs"] if "build" in j["title"]]
        self.assertEqual(len(build_jobs), 1)
        self.assertEqual(build_jobs[0]["state"], "proposed")

        # 5. Verify the command has resolved inputs
        # API returns command as a list (already decoded by _job_to_dict)
        cmd = build_jobs[0]["command"]
        self.assertEqual(cmd, ["echo", "building", "/home/mehdi/workspace/Agent-OS"])

        # 6. Verify workflow execution is listed
        status, executions = self._call("GET", "/api/workflow-executions")
        self.assertEqual(status, 200)
        self.assertEqual(len(executions["executions"]), 1)

        # 7. Verify workflow template is listed
        status, templates = self._call("GET", "/api/workflows")
        self.assertEqual(status, 200)
        self.assertEqual(len(templates["workflows"]), 1)

    def test_workflow_with_human_approval_node(self):
        """Workflow with HUMAN_APPROVAL node should not create a job for it."""
        status, wf = self._call("POST", "/api/workflows", {
            "title": "Approval Pipeline",
            "description": "Test with approval gate",
            "default_executor": "fake-executor",
            "inputs_schema": {},
            "nodes": [
                {
                    "id": "test",
                    "action_type": "execute_job",
                    "metadata": {
                        "command": ["echo", "testing"],
                        "actions": ["run_command"],
                        "workspace_paths": ["/tmp"],
                    },
                    "depends_on": [],
                },
                {
                    "id": "approval",
                    "action_type": "human_approval",
                    "metadata": {},
                    "depends_on": ["test"],
                },
            ],
        })
        self.assertEqual(status, 201)

        status, execution = self._call("POST", f"/api/workflows/{wf['id']}/execute", {
            "inputs": {},
        })
        self.assertEqual(status, 200)

        # Only the "test" job should exist, not the approval node
        status, jobs = self._call("GET", "/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(len(jobs["jobs"]), 1)
        self.assertIn("test", jobs["jobs"][0]["title"])

    def test_workflow_execution_with_multiple_root_nodes(self):
        """Workflow with multiple root nodes should create multiple jobs."""
        status, wf = self._call("POST", "/api/workflows", {
            "title": "Parallel Pipeline",
            "description": "Two independent root nodes",
            "default_executor": "fake-executor",
            "inputs_schema": {},
            "nodes": [
                {
                    "id": "lint",
                    "action_type": "execute_job",
                    "metadata": {
                        "command": ["echo", "linting"],
                        "actions": ["run_command"],
                        "workspace_paths": ["/tmp"],
                    },
                    "depends_on": [],
                },
                {
                    "id": "format",
                    "action_type": "execute_job",
                    "metadata": {
                        "command": ["echo", "formatting"],
                        "actions": ["run_command"],
                        "workspace_paths": ["/tmp"],
                    },
                    "depends_on": [],
                },
            ],
        })
        self.assertEqual(status, 201)

        status, execution = self._call("POST", f"/api/workflows/{wf['id']}/execute", {
            "inputs": {},
        })
        self.assertEqual(status, 200)

        # Both root nodes should have jobs
        status, jobs = self._call("GET", "/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual(len(jobs["jobs"]), 2)


if __name__ == "__main__":
    unittest.main()
