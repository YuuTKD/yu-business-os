"""Governance Validator for YU Business OS 2.0 (Phase A).

Turns a proposed action into a machine judgement:

    GO                          allowed to proceed
    OWNER_APPROVAL_REQUIRED     needs ゆうさん's explicit approval first
    FIX                         disallowed as-is; adjust and retry
    STOP                        hard block; do not proceed

Design principles (from the 2.0 governance policies):
    * default deny — unknown agent / unknown action → STOP
    * secrets, credentials and .env contents are never output → STOP
    * external send / deploy / scheduler / production writes → owner approval
    * CRITICAL risk → STOP
    * a granted owner approval only helps if the acting agent also holds the
      matching permission (still default deny on the agent).

This module performs **no I/O to external systems**. It only reasons over the
registries, the policy file, and the request it is handed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from core.registry.agent_registry import AgentRegistry
from core.registry.models import (
    AgentStatus,
    Decision,
    GovernanceResult,
    RiskLevel,
    SkillStatus,
)
from core.registry.skill_registry import SkillRegistry

try:
    import yaml as _yaml  # type: ignore

    def _load_yaml(text: str):
        return _yaml.safe_load(text)
except Exception:  # pragma: no cover
    from core.registry._yaml_min import safe_load as _load_yaml


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEFAULT_POLICY_PATH = os.path.join("configs", "governance", "policies.yaml")


# ── action taxonomy ───────────────────────────────────────────
# Hard-stop actions: never allowed, even with owner approval.
STOP_ACTIONS = {
    "secret_output", "secret_display", "token_output", "token_display",
    "credentials_read", "credentials_output", "env_output", "env_display",
    "main_direct_commit", "high_risk_auto_merge", "auto_merge_high_risk",
    "existing_file_delete", "existing_file_move",
    "acquisition_resume", "tree_beauty_activate", "daily_post_limit_change",
}

# Actions that require explicit owner approval AND a matching agent permission.
EXTERNAL_SEND_ACTIONS = {
    "line_send", "line_notify", "gmail_send", "email_send",
    "threads_post", "google_post", "sns_post", "instagram_post", "dm_send",
}
DEPLOY_ACTIONS = {"cloud_run_deploy", "deploy", "cloud_run_env_change"}
SCHEDULER_ACTIONS = {
    "scheduler_create", "scheduler_update", "scheduler_enable",
    "scheduler_run", "scheduler_delete", "scheduler_on", "scheduler_off",
}
PRODUCTION_WRITE_ACTIONS = {
    "gcs_write", "gcs_delete", "sheets_write", "image_library_write",
}

# Read-only / safe actions.
SAFE_ACTIONS = {
    "audit_read", "registry_lookup", "read_status", "validate_registry",
    "governance_check", "generate_doc", "run_tests", "dry_run",
}

# Review actions: decision follows the computed risk level (not a raw side
# effect). Used by the PR governance gate. CRITICAL / blocked-path / hard-stop
# checks still run first, so those always win over the risk mapping below.
REVIEW_ACTIONS = {"pr_change_review", "pr_merge"}

HIGH_RISK_PATH_PREFIXES = ("core/", "scripts/", "agents/", "config/", "configs/",
                           "workflows/", "apps/")
BLOCKED_PATH_PREFIXES = ("scripts/acquisition/",)


@dataclass
class GovernanceRequest:
    agent_id: str
    action: str
    skill_id: Optional[str] = None
    target_business: Optional[str] = None
    file_paths: List[str] = field(default_factory=list)
    risk_level: Optional[str] = None
    owner_approved: bool = False
    branch_name: Optional[str] = None


class GovernanceValidator:
    def __init__(
        self,
        policy_path: Optional[str] = None,
        skill_registry: Optional[SkillRegistry] = None,
        agent_registry: Optional[AgentRegistry] = None,
        repo_root: Optional[str] = None,
    ):
        self.repo_root = os.path.abspath(repo_root or _repo_root())
        rel = policy_path or DEFAULT_POLICY_PATH
        self.policy_path = rel if os.path.isabs(rel) else os.path.join(self.repo_root, rel)
        self.skills = skill_registry or SkillRegistry(repo_root=self.repo_root)
        self.agents = agent_registry or AgentRegistry(repo_root=self.repo_root)
        self._policies: dict = {}
        self._policy_error: Optional[str] = None
        self._load_policies()

    def _load_policies(self) -> None:
        try:
            with open(self.policy_path, "r", encoding="utf-8") as fh:
                self._policies = _load_yaml(fh.read()) or {}
        except FileNotFoundError:
            self._policy_error = f"policy file not found: {self.policy_path}"
        except Exception as exc:
            self._policy_error = f"failed to parse policies: {exc}"

    @property
    def policy_error(self) -> Optional[str]:
        return self._policy_error

    # ── main decision ─────────────────────────────────────────
    def decide(self, request: GovernanceRequest) -> GovernanceResult:
        reasons: List[str] = []
        matched: List[str] = []
        action = (request.action or "").strip().lower()
        risk = (request.risk_level or "").strip().upper()

        # 0. Config integrity — if policies could not load, fail safe.
        if self._policy_error:
            return GovernanceResult(Decision.STOP.value,
                                    [f"governance config error: {self._policy_error}"],
                                    ["config_integrity"], RiskLevel.CRITICAL.value)

        # 1. Unknown / empty action → default deny.
        if not action:
            return GovernanceResult(Decision.STOP.value,
                                    ["empty action (default deny)"],
                                    ["default_deny"], RiskLevel.HIGH.value)

        # 2. Agent must be known and usable.
        agent_res = self.agents.resolve(request.agent_id, request.target_business)
        if agent_res.status == AgentStatus.NOT_FOUND.value:
            return GovernanceResult(Decision.STOP.value,
                                    [f"unknown agent '{request.agent_id}' (default deny)"],
                                    ["default_deny", "agent_unknown"], RiskLevel.HIGH.value)
        if agent_res.status == AgentStatus.INVALID_CONFIG.value:
            return GovernanceResult(Decision.STOP.value,
                                    [f"agent registry invalid: {agent_res.reason}"],
                                    ["config_integrity"], RiskLevel.CRITICAL.value)
        agent = agent_res.definition

        # 3. Blocked paths (scripts/acquisition/**) → STOP regardless of action.
        for path in request.file_paths:
            norm = path.replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            if any(norm.startswith(pref) for pref in BLOCKED_PATH_PREFIXES):
                return GovernanceResult(Decision.STOP.value,
                                        [f"touches blocked path '{path}' (scripts/acquisition frozen)"],
                                        ["no_existing_file_delete", "acquisition_frozen"],
                                        RiskLevel.CRITICAL.value)

        # 4. Hard-stop actions.
        if action in STOP_ACTIONS:
            return GovernanceResult(Decision.STOP.value,
                                    [f"action '{action}' is prohibited (hard stop)"],
                                    ["no_secret_output", "hard_stop"], RiskLevel.CRITICAL.value)

        # 5. Branch protection: writing on main is a STOP.
        write_like = (action not in SAFE_ACTIONS)
        if write_like and (request.branch_name or "").strip() == "main":
            return GovernanceResult(Decision.STOP.value,
                                    ["direct changes on 'main' are not allowed"],
                                    ["no_main_direct_commit"], RiskLevel.HIGH.value)

        # 6. Skill validity (if a skill is named).
        if request.skill_id:
            skill_res = self.skills.resolve(request.skill_id, request.target_business)
            if skill_res.status == SkillStatus.INVALID_CONFIG.value:
                return GovernanceResult(Decision.STOP.value,
                                        [f"skill registry invalid: {skill_res.reason}"],
                                        ["config_integrity"], RiskLevel.CRITICAL.value)
            if skill_res.status == SkillStatus.FORBIDDEN.value:
                return GovernanceResult(Decision.STOP.value,
                                        [f"skill '{request.skill_id}' forbidden: {skill_res.reason}"],
                                        ["default_deny"], RiskLevel.HIGH.value)
            # Skill's own prohibited actions.
            if action in self.skills.prohibited_actions(request.skill_id):
                return GovernanceResult(Decision.STOP.value,
                                        [f"action '{action}' is in skill '{request.skill_id}' prohibited list"],
                                        ["skill_prohibited_action"], RiskLevel.HIGH.value)

        # 7. Agent stop conditions.
        if agent and action in {c.strip().lower() for c in agent.stop_conditions}:
            return GovernanceResult(Decision.STOP.value,
                                    [f"action '{action}' matches agent stop condition"],
                                    ["agent_stop_condition"], RiskLevel.HIGH.value)

        # 8. CRITICAL declared risk → STOP.
        if risk == RiskLevel.CRITICAL.value:
            return GovernanceResult(Decision.STOP.value,
                                    ["declared risk is CRITICAL"],
                                    ["critical_risk_stop"], RiskLevel.CRITICAL.value)

        # 8b. PR review actions: decision follows the computed risk level.
        #     (CRITICAL / blocked / hard-stop already handled above.)
        if action in REVIEW_ACTIONS:
            eff_risk = risk or self._risk_for(request)
            if eff_risk == RiskLevel.HIGH.value:
                if request.owner_approved:
                    return GovernanceResult(
                        Decision.GO.value,
                        ["HIGH-risk change approved by owner "
                         "(auto-merge remains forbidden — human must merge)"],
                        ["no_auto_merge_for_high_risk"], RiskLevel.HIGH.value)
                return GovernanceResult(
                    Decision.OWNER_APPROVAL_REQUIRED.value,
                    ["HIGH-risk PR requires owner approval before merge"],
                    ["no_auto_merge_for_high_risk"], RiskLevel.HIGH.value)
            return GovernanceResult(
                Decision.GO.value,
                [f"review change classified {eff_risk or RiskLevel.LOW.value} risk"],
                ["review_ok"], eff_risk or RiskLevel.LOW.value)

        # 9. Owner-approval gated categories.
        gated = self._categorise_gated(action, agent)
        if gated is not None:
            category, has_permission, policy = gated
            matched.append(policy)
            if not request.owner_approved:
                reasons.append(f"'{action}' ({category}) requires owner approval")
                return GovernanceResult(Decision.OWNER_APPROVAL_REQUIRED.value,
                                        reasons, matched, RiskLevel.HIGH.value)
            if not has_permission:
                reasons.append(f"agent '{request.agent_id}' lacks {category} permission (default deny)")
                return GovernanceResult(Decision.STOP.value, reasons,
                                        matched + ["default_deny"], RiskLevel.HIGH.value)
            reasons.append(f"'{action}' approved by owner and permitted for agent")
            return GovernanceResult(Decision.GO.value, reasons, matched, RiskLevel.HIGH.value)

        # 10. Safe / read-only actions are always allowed.
        if action in SAFE_ACTIONS:
            return GovernanceResult(Decision.GO.value,
                                    [f"'{action}' is read-only / safe"],
                                    ["safe_action"], self._risk_for(request))

        # 11. Agent-declared owner-approval conditions that specifically match
        #     this action (does NOT blanket every action for the agent).
        if agent and not request.owner_approved:
            agent_conditions = {c.strip().lower() for c in agent.owner_approval_conditions}
            if action in agent_conditions:
                return GovernanceResult(Decision.OWNER_APPROVAL_REQUIRED.value,
                                        [f"action '{action}' matches agent owner-approval condition"],
                                        ["agent_owner_approval"], self._risk_for(request))

        # 12. Known-but-unclassified write action on high-risk paths → FIX
        #     (needs an explicit action mapping before it can be judged GO).
        if self._touches_high_risk_paths(request.file_paths):
            return GovernanceResult(Decision.FIX.value,
                                    [f"'{action}' affects high-risk paths but is not a "
                                     "recognised safe action; classify it explicitly"],
                                    ["unclassified_high_risk"], RiskLevel.HIGH.value)

        # 13. Default deny for anything still unrecognised.
        return GovernanceResult(Decision.STOP.value,
                                [f"unrecognised action '{action}' (default deny)"],
                                ["default_deny"], RiskLevel.MEDIUM.value)

    # ── helpers ───────────────────────────────────────────────
    def _categorise_gated(self, action, agent):
        """Return (category, agent_has_permission, policy_id) or None."""
        if action in EXTERNAL_SEND_ACTIONS:
            return ("external_send",
                    bool(agent and agent.external_send_permission),
                    "no_external_send_without_owner_approval")
        if action in DEPLOY_ACTIONS:
            return ("deploy",
                    bool(agent and agent.deploy_permission),
                    "no_deploy_without_owner_approval")
        if action in SCHEDULER_ACTIONS:
            return ("scheduler",
                    bool(agent and agent.scheduler_permission),
                    "no_scheduler_change_without_owner_approval")
        if action in PRODUCTION_WRITE_ACTIONS:
            return ("production_write",
                    bool(agent and agent.write_permissions),
                    "no_production_write_without_owner_approval")
        return None

    def _touches_high_risk_paths(self, file_paths) -> bool:
        for path in file_paths or []:
            norm = path.replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            if any(norm.startswith(pref) for pref in HIGH_RISK_PATH_PREFIXES):
                return True
        return False

    def _risk_for(self, request) -> str:
        if request.risk_level:
            return request.risk_level.strip().upper()
        if self._touches_high_risk_paths(request.file_paths):
            return RiskLevel.HIGH.value
        return RiskLevel.LOW.value


def load_default() -> GovernanceValidator:
    return GovernanceValidator()
