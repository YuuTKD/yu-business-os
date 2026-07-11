"""Unit tests for the Agent Registry loader (Phase A)."""

import os
import sys
import tempfile
import textwrap
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.registry.agent_registry import AgentRegistry
from core.registry.skill_registry import SkillRegistry
from core.registry.models import AgentStatus


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))


class AgentRegistryRealTest(unittest.TestCase):
    def setUp(self):
        self.agents = AgentRegistry().load()
        self.skills = SkillRegistry().load()

    def test_09_loads_clean(self):
        self.assertIsNone(self.agents.load_error)
        self.assertGreaterEqual(len(self.agents.all_agents()), 8)

    def test_10_unknown_agent_not_found(self):
        res = self.agents.resolve("ghost-agent")
        self.assertEqual(res.status, AgentStatus.NOT_FOUND.value)

    def test_11_inactive_agent_returns_inactive(self):
        res = self.agents.resolve("cfo-agent")
        self.assertEqual(res.status, AgentStatus.INACTIVE.value)

    def test_12_15_default_deny_all_agents(self):
        for agent in self.agents.all_agents():
            self.assertFalse(agent.external_send_permission, agent.id)
            self.assertFalse(agent.deploy_permission, agent.id)
            self.assertFalse(agent.scheduler_permission, agent.id)
            self.assertFalse(agent.secret_access, agent.id)

    def test_16_skill_references_all_defined(self):
        issues = self.agents.validate_references(self.skills)
        self.assertEqual(issues, [], msg=[i.line() for i in issues])

    def test_active_agent_allowed_when_no_conditions(self):
        # codex-review-agent is active with no owner_approval_conditions.
        res = self.agents.resolve("codex-review-agent")
        self.assertEqual(res.status, AgentStatus.ALLOWED.value)

    def test_active_agent_with_conditions_needs_owner(self):
        # claude-code-implementation-agent has owner_approval_conditions.
        res = self.agents.resolve("claude-code-implementation-agent")
        self.assertEqual(res.status, AgentStatus.OWNER_APPROVAL_REQUIRED.value)


class AgentRegistryFixtureTest(unittest.TestCase):
    def test_elevated_permission_flagged_stop(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _write(os.path.join(tmp.name, "configs", "agents", "registry.yaml"), """
            version: 1
            agents:
              - id: rogue
                name: Rogue
                deploy_permission: true
                active: true
        """)
        reg = AgentRegistry(repo_root=tmp.name).load()
        self.assertTrue(any(i.field == "deploy_permission" and i.severity == "STOP"
                            for i in reg.issues()))

    def test_unknown_skill_reference_flagged(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _write(os.path.join(tmp.name, "configs", "agents", "registry.yaml"), """
            version: 1
            agents:
              - id: refbad
                name: Ref Bad
                skills:
                  - no-such-skill
                active: true
        """)
        _write(os.path.join(tmp.name, "configs", "skills", "registry.yaml"), """
            version: 1
            skills:
              - id: real-skill
                name: Real
                active: true
        """)
        agents = AgentRegistry(repo_root=tmp.name).load()
        skills = SkillRegistry(repo_root=tmp.name).load()
        issues = agents.validate_references(skills)
        self.assertTrue(any("no-such-skill" in i.reason for i in issues))


if __name__ == "__main__":
    unittest.main()
