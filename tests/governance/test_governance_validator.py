"""Unit tests for the Governance Validator (Phase A)."""

import os
import sys
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance.validator import GovernanceValidator, GovernanceRequest
from core.registry.models import Decision


class GovernanceValidatorTest(unittest.TestCase):
    def setUp(self):
        self.gov = GovernanceValidator()
        # An active agent that carries owner-approval conditions.
        self.actor = "claude-code-implementation-agent"

    def decide(self, **kwargs):
        kwargs.setdefault("agent_id", self.actor)
        return self.gov.decide(GovernanceRequest(**kwargs))

    # ── hard STOP actions ─────────────────────────────────────
    def test_17_secret_output_stop(self):
        self.assertEqual(self.decide(action="secret_output").decision, Decision.STOP.value)

    def test_18_credentials_read_stop(self):
        self.assertEqual(self.decide(action="credentials_read").decision, Decision.STOP.value)

    def test_19_env_output_stop(self):
        self.assertEqual(self.decide(action="env_output").decision, Decision.STOP.value)

    def test_20_main_direct_commit_stop(self):
        self.assertEqual(self.decide(action="main_direct_commit").decision, Decision.STOP.value)

    def test_21_high_risk_auto_merge_stop(self):
        self.assertEqual(self.decide(action="high_risk_auto_merge").decision, Decision.STOP.value)

    def test_acquisition_resume_stop(self):
        self.assertEqual(self.decide(action="acquisition_resume").decision, Decision.STOP.value)

    def test_tree_beauty_activate_stop(self):
        self.assertEqual(self.decide(action="tree_beauty_activate").decision, Decision.STOP.value)

    def test_daily_post_limit_change_stop(self):
        self.assertEqual(self.decide(action="daily_post_limit_change").decision, Decision.STOP.value)

    # ── owner-approval gated ──────────────────────────────────
    def test_22_deploy_needs_owner_approval(self):
        self.assertEqual(self.decide(action="cloud_run_deploy").decision,
                         Decision.OWNER_APPROVAL_REQUIRED.value)

    def test_23_scheduler_change_needs_owner_approval(self):
        self.assertEqual(self.decide(action="scheduler_update").decision,
                         Decision.OWNER_APPROVAL_REQUIRED.value)

    def test_24_line_send_needs_owner_approval(self):
        self.assertEqual(self.decide(action="line_send").decision,
                         Decision.OWNER_APPROVAL_REQUIRED.value)

    def test_25_gcs_write_needs_owner_approval(self):
        self.assertEqual(self.decide(action="gcs_write").decision,
                         Decision.OWNER_APPROVAL_REQUIRED.value)

    def test_deploy_with_approval_but_no_permission_stops(self):
        # Owner approves, but the agent lacks deploy permission → default deny STOP.
        res = self.decide(action="cloud_run_deploy", owner_approved=True)
        self.assertEqual(res.decision, Decision.STOP.value)

    # ── safe / read-only ──────────────────────────────────────
    def test_26_audit_read_go(self):
        self.assertEqual(self.decide(action="audit_read").decision, Decision.GO.value)

    def test_registry_lookup_go(self):
        self.assertEqual(self.decide(action="registry_lookup").decision, Decision.GO.value)

    # ── default deny ──────────────────────────────────────────
    def test_27_unknown_action_stop(self):
        self.assertEqual(self.decide(action="frobnicate_everything").decision, Decision.STOP.value)

    def test_28_unknown_agent_stop(self):
        res = self.gov.decide(GovernanceRequest(agent_id="ghost", action="audit_read"))
        self.assertEqual(res.decision, Decision.STOP.value)

    def test_29_empty_action_default_deny_stop(self):
        self.assertEqual(self.decide(action="").decision, Decision.STOP.value)

    # ── path & branch protections ─────────────────────────────
    def test_blocked_acquisition_path_stop(self):
        res = self.decide(action="dry_run", file_paths=["scripts/acquisition/run.js"])
        self.assertEqual(res.decision, Decision.STOP.value)

    def test_main_branch_write_stop(self):
        # A write-like action (commit) on main must be blocked by branch protection.
        res = self.decide(action="commit", branch_name="main")
        self.assertEqual(res.decision, Decision.STOP.value)
        self.assertTrue(any("main" in r for r in res.reasons))

    def test_critical_risk_stop(self):
        res = self.decide(action="audit_read", risk_level="CRITICAL")
        self.assertEqual(res.decision, Decision.STOP.value)

    def test_skill_prohibited_action_stop(self):
        # pre-deploy-qa prohibits cloud_run_deploy; naming the skill escalates to STOP.
        res = self.decide(action="cloud_run_deploy", skill_id="pre-deploy-qa")
        self.assertEqual(res.decision, Decision.STOP.value)


if __name__ == "__main__":
    unittest.main()
