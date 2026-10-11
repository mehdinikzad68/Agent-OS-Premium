# Agent OS — Human-Supervised Agent Operating System
# Copyright (c) 2026 Mehdi Nikzad Semeskandi
# SPDX-License-Identifier: Apache-2.0
# Author: Mehdi Nikzad Semeskandi

"""Tests for configurable workflows (Phase 9).

Covers:
- Workflow template creation with nodes
- Workflow execution creates a mission and fans out root jobs
- Node action_type validation
- Input parameter resolution in commands
- Workflow template listing and retrieval
- Workflow execution listing and retrieval
"""

from __future__ import annotations

import json
import shutil
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent_os.adapters.fake import FakeExecutor
from agent_os.models import (
    ApprovalDecision,
    JobState,
    NodeActionType,
    Principal,
)
from agent_os.service import ControlService

T0 = datetime(2026, 10, 3, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)

TMP = Path(__file__).resolve().parent.parent / ".testtmp"


class WorkflowModelTest(unittest.TestCase):
    """Test the workflow data models."""

    def test_node_action_type_values(self):
        self.assertEqual(NodeActionType.EXECUTE_JOB.value, "execute_job")
        self.assertEqual(NodeActionType.HUMAN_APPROVAL.value, "human_approval")
        self.assertEqual(NodeActionType.CONDITIONAL_BRANCH.value, "conditional_branch")

    def test_workflow_template_dataclass(self):
        from agent_os.models import WorkflowTemplate
        t = WorkflowTemplate(
            id="wf-1", title="Test", description="",
            created_at="2026-10-03T10:00:00+00:00", version=1,
            inputs_schema={}, default_executor="fake-executor",
        )
        self.assertEqual(t.id, "wf-1")
        self.assertEqual(t.version, 1)

    def test_workflow_node_dataclass(self):
        from agent_os.models import WorkflowNode
        n = WorkflowNode(
            id="n1", workflow_id="wf-1",
            action_type=NodeActionType.EXECUTE_JOB,
            metadata={"command": ["echo", "hi"]},
            depends_on=("root",),
        )
        self.assertEqual(n.depends_on, ("root",))

    def test_workflow_execution_dataclass(self):
        from agent_os.models import WorkflowExecution
        e = WorkflowExecution(
            id="wfx-1", workflow_id="wf-1", mission_id="m-1",
            status="active", inputs={"target_path": "/tmp"},
            created_at="2026-10-03T10:00:00+00:00",
        )
        self.assertEqual(e.status, "active")
        self.assertEqual(e.inputs["target_path"], "/tmp")


class WorkflowServiceTest(unittest.TestCase):
    """Test workflow operations through ControlService."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db_path = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.svc = ControlService(self.db_path)

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(TMP, ignore_errors=True)

    def _sample_nodes(self):
        return [
            {
                "id": "step1",
                "action_type": "execute_job",
                "metadata": {
                    "command": ["echo", "hello"],
                    "actions": ["run_command"],
                    "workspace_paths": ["/tmp"],
                },
                "depends_on": [],
            },
            {
                "id": "step2",
                "action_type": "execute_job",
                "metadata": {
                    "command": ["echo", "world"],
                    "actions": ["run_command"],
                    "workspace_paths": ["/tmp"],
                },
                "depends_on": ["step1"],
            },
        ]

    def test_create_workflow_template(self):
        result = self.svc.create_workflow_template(
            title="Test Workflow",
            description="A test",
            inputs_schema={"type": "object"},
            default_executor="fake-executor",
            nodes=self._sample_nodes(),
            now=T0,
        )
        self.assertEqual(result["title"], "Test Workflow")
        self.assertEqual(result["version"], 1)
        self.assertEqual(len(result["nodes"]), 2)

    def test_get_workflow_template(self):
        created = self.svc.create_workflow_template(
            title="Test", description="", inputs_schema={},
            default_executor="fake-executor", nodes=self._sample_nodes(), now=T0,
        )
        fetched = self.svc.get_workflow_template(created["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Test")
        self.assertEqual(len(fetched["nodes"]), 2)

    def test_get_workflow_template_not_found(self):
        result = self.svc.get_workflow_template("nonexistent")
        self.assertIsNone(result)

    def test_list_workflow_templates(self):
        nodes1 = [
            {"id": "wf1_step1", "action_type": "execute_job", "metadata": {}, "depends_on": []},
        ]
        nodes2 = [
            {"id": "wf2_step1", "action_type": "execute_job", "metadata": {}, "depends_on": []},
        ]
        self.svc.create_workflow_template(
            title="WF1", description="", inputs_schema={},
            default_executor="fake-executor", nodes=nodes1, now=T0,
        )
        self.svc.create_workflow_template(
            title="WF2", description="", inputs_schema={},
            default_executor="fake-executor", nodes=nodes2, now=T0,
        )
        result = self.svc.list_workflow_templates()
        self.assertEqual(len(result), 2)

    def test_execute_workflow_creates_mission_and_jobs(self):
        template = self.svc.create_workflow_template(
            title="Exec Test", description="", inputs_schema={},
            default_executor="fake-executor", nodes=self._sample_nodes(), now=T0,
        )
        execution = self.svc.execute_workflow(
            template_id=template["id"],
            inputs={"target_path": "/home/test"},
            now=T0,
        )
        self.assertEqual(execution["status"], "active")
        self.assertIn("mission_id", execution)

        # Verify mission was created
        mission = self.svc.store.get_mission(execution["mission_id"])
        self.assertIsNotNone(mission)
        self.assertEqual(mission.state.value, "active")

        # Verify root job was proposed (step1 has no dependencies)
        jobs = self.svc.store.list_jobs()
        self.assertTrue(len(jobs) >= 1)
        root_jobs = [j for j in jobs if "step1" in j.title]
        self.assertEqual(len(root_jobs), 1)
        self.assertEqual(root_jobs[0].state, JobState.PROPOSED)

    def test_execute_workflow_not_found(self):
        with self.assertRaises(KeyError):
            self.svc.execute_workflow("nonexistent", {}, now=T0)

    def test_get_workflow_execution(self):
        template = self.svc.create_workflow_template(
            title="Get Test", description="", inputs_schema={},
            default_executor="fake-executor", nodes=self._sample_nodes(), now=T0,
        )
        execution = self.svc.execute_workflow(
            template_id=template["id"],
            inputs={}, now=T0,
        )
        fetched = self.svc.get_workflow_execution(execution["id"])
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], execution["id"])

    def test_list_workflow_executions(self):
        template = self.svc.create_workflow_template(
            title="List Test", description="", inputs_schema={},
            default_executor="fake-executor", nodes=self._sample_nodes(), now=T0,
        )
        self.svc.execute_workflow(template["id"], {}, now=T0)
        self.svc.execute_workflow(template["id"], {}, now=T1)
        result = self.svc.list_workflow_executions()
        self.assertEqual(len(result), 2)

    def test_human_approval_node_no_job(self):
        """HUMAN_APPROVAL nodes should not create job proposals."""
        nodes = [
            {
                "id": "approval_gate_1",
                "action_type": "human_approval",
                "metadata": {},
                "depends_on": [],
            },
        ]
        template = self.svc.create_workflow_template(
            title="Approval WF", description="", inputs_schema={},
            default_executor="fake-executor", nodes=nodes, now=T0,
        )
        execution = self.svc.execute_workflow(template["id"], {}, now=T0)
        jobs = self.svc.store.list_jobs()
        # No jobs should be created for HUMAN_APPROVAL nodes
        self.assertEqual(len(jobs), 0)

    def test_conditional_branch_node_no_job(self):
        """CONDITIONAL_BRANCH nodes should not create job proposals."""
        nodes = [
            {
                "id": "branch_1",
                "action_type": "conditional_branch",
                "metadata": {},
                "depends_on": [],
            },
        ]
        template = self.svc.create_workflow_template(
            title="Branch WF", description="", inputs_schema={},
            default_executor="fake-executor", nodes=nodes, now=T0,
        )
        execution = self.svc.execute_workflow(template["id"], {}, now=T0)
        jobs = self.svc.store.list_jobs()
        self.assertEqual(len(jobs), 0)

    def test_input_parameter_resolution(self):
        """{{inputs.xxx}} placeholders in commands should be resolved."""
        nodes = [
            {
                "id": "param_step1",
                "action_type": "execute_job",
                "metadata": {
                    "command": ["echo", "{{inputs.target_path}}"],
                    "actions": ["run_command"],
                    "workspace_paths": ["/tmp"],
                },
                "depends_on": [],
            },
        ]
        template = self.svc.create_workflow_template(
            title="Param Test", description="", inputs_schema={},
            default_executor="fake-executor", nodes=nodes, now=T0,
        )
        execution = self.svc.execute_workflow(
            template["id"],
            inputs={"target_path": "/home/mehdi/workspace"},
            now=T0,
        )
        jobs = self.svc.store.list_jobs()
        self.assertEqual(len(jobs), 1)
        # The command should have the placeholder resolved
        from agent_os.models import decode_command
        cmd = decode_command(jobs[0].command)
        self.assertEqual(cmd[0], "echo")
        self.assertEqual(cmd[1], "/home/mehdi/workspace")


class WorkflowApiTest(unittest.TestCase):
    """Test workflow endpoints through the API layer."""

    def setUp(self):
        TMP.mkdir(exist_ok=True)
        self.db = TMP / f"{self.id().rsplit('.', 1)[-1]}.db"
        if self.db.exists():
            self.db.unlink()
        self.svc = ControlService(self.db)
        from agent_os.api import AgentOSApi
        self.api = AgentOSApi(self.svc, token="secret")

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(TMP, ignore_errors=True)

    def _call(self, method, path, body=None):
        return self.api.handle(method, path, body)

    def test_api_create_workflow(self):
        status, payload = self._call("POST", "/api/workflows", {
            "title": "API WF",
            "description": "test",
            "default_executor": "fake-executor",
            "inputs_schema": {},
            "nodes": [
                {
                    "id": "n1",
                    "action_type": "execute_job",
                    "metadata": {"command": ["echo", "hi"]},
                    "depends_on": [],
                }
            ],
        })
        self.assertEqual(status, 201)
        self.assertEqual(payload["title"], "API WF")
        self.assertEqual(len(payload["nodes"]), 1)

    def test_api_create_workflow_invalid_action_type(self):
        status, payload = self._call("POST", "/api/workflows", {
            "title": "Bad WF",
            "description": "",
            "default_executor": "fake-executor",
            "inputs_schema": {},
            "nodes": [
                {
                    "id": "n1",
                    "action_type": "invalid_type",
                    "metadata": {},
                    "depends_on": [],
                }
            ],
        })
        self.assertEqual(status, 400)

    def test_api_create_workflow_missing_node_id(self):
        status, payload = self._call("POST", "/api/workflows", {
            "title": "Bad WF",
            "description": "",
            "default_executor": "fake-executor",
            "inputs_schema": {},
            "nodes": [
                {
                    "action_type": "execute_job",
                    "metadata": {},
                    "depends_on": [],
                }
            ],
        })
        self.assertEqual(status, 400)

    def test_api_list_workflows(self):
        self._call("POST", "/api/workflows", {
            "title": "WF1", "description": "", "default_executor": "fake-executor",
            "inputs_schema": {}, "nodes": [],
        })
        status, payload = self._call("GET", "/api/workflows")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["workflows"]), 1)

    def test_api_get_workflow(self):
        _, created = self._call("POST", "/api/workflows", {
            "title": "WF1", "description": "", "default_executor": "fake-executor",
            "inputs_schema": {}, "nodes": [],
        })
        status, payload = self._call("GET", f"/api/workflows/{created['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["title"], "WF1")

    def test_api_execute_workflow(self):
        _, created = self._call("POST", "/api/workflows", {
            "title": "Exec WF", "description": "", "default_executor": "fake-executor",
            "inputs_schema": {},
            "nodes": [
                {
                    "id": "n1",
                    "action_type": "execute_job",
                    "metadata": {"command": ["echo", "hi"]},
                    "depends_on": [],
                }
            ],
        })
        status, payload = self._call("POST", f"/api/workflows/{created['id']}/execute", {
            "inputs": {"key": "value"},
        })
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "active")
        self.assertIn("mission_id", payload)

    def test_api_list_executions(self):
        _, created = self._call("POST", "/api/workflows", {
            "title": "WF1", "description": "", "default_executor": "fake-executor",
            "inputs_schema": {}, "nodes": [],
        })
        self._call("POST", f"/api/workflows/{created['id']}/execute", {"inputs": {}})
        status, payload = self._call("GET", "/api/workflow-executions")
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["executions"]), 1)

    def test_api_get_execution(self):
        _, created = self._call("POST", "/api/workflows", {
            "title": "WF1", "description": "", "default_executor": "fake-executor",
            "inputs_schema": {}, "nodes": [],
        })
        _, exec_result = self._call("POST", f"/api/workflows/{created['id']}/execute", {"inputs": {}})
        status, payload = self._call("GET", f"/api/workflow-executions/{exec_result['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], exec_result["id"])


if __name__ == "__main__":
    unittest.main()
