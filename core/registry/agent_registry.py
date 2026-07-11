"""Agent Registry loader for YU Business OS 2.0 (Phase A).

Single source of truth for agent identity, permissions (default deny), owner
approval conditions, stop conditions, and which skills each agent may use.

Safety guarantees:
    * Every agent defaults to no external send / no deploy / no scheduler /
      no secret access. Any agent claiming those is flagged by validation.
    * Agent → skill references are checked against the SkillRegistry.
    * Load failures fail safe (INVALID_CONFIG), never raise to the caller.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .models import (
    AgentDefinition,
    AgentStatus,
    RegistryResult,
    Severity,
    ValidationIssue,
)
from .skill_registry import SkillRegistry

try:
    import yaml as _yaml  # type: ignore

    def _load_yaml(text: str):
        return _yaml.safe_load(text)
except Exception:  # pragma: no cover
    from ._yaml_min import safe_load as _load_yaml


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEFAULT_REGISTRY_PATH = os.path.join("configs", "agents", "registry.yaml")


class AgentRegistry:
    def __init__(self, path: Optional[str] = None, repo_root: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root or _repo_root())
        rel = path or DEFAULT_REGISTRY_PATH
        self.path = rel if os.path.isabs(rel) else os.path.join(self.repo_root, rel)
        self._agents: Dict[str, AgentDefinition] = {}
        self._issues: List[ValidationIssue] = []
        self._duplicate_ids: set = set()
        self._loaded = False
        self._load_error: Optional[str] = None

    # ── loading ───────────────────────────────────────────────
    def load(self) -> "AgentRegistry":
        self._agents = {}
        self._issues = []
        self._duplicate_ids = set()
        self._load_error = None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = _load_yaml(fh.read())
        except FileNotFoundError:
            self._load_error = f"registry file not found: {self.path}"
            self._loaded = True
            return self
        except Exception as exc:
            self._load_error = f"failed to parse registry: {exc}"
            self._loaded = True
            return self

        entries = (data or {}).get("agents") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            self._load_error = "registry has no 'agents' list"
            self._loaded = True
            return self

        for raw in entries:
            if not isinstance(raw, dict):
                self._issues.append(ValidationIssue(
                    Severity.FIX.value, self._relpath(), "agents", "entry is not a mapping"))
                continue
            agent = AgentDefinition.from_dict(raw)
            if not agent.id:
                self._issues.append(ValidationIssue(
                    Severity.STOP.value, self._relpath(), "id", "agent entry missing id"))
                continue
            if agent.id in self._agents:
                self._duplicate_ids.add(agent.id)
                self._issues.append(ValidationIssue(
                    Severity.FIX.value, self._relpath(), "id",
                    "duplicate agent id", entity_id=agent.id))
                continue
            self._validate_entry(agent)
            self._agents[agent.id] = agent
        self._loaded = True
        return self

    def _validate_entry(self, agent: AgentDefinition) -> None:
        # Default-deny enforcement: elevated permissions must be justified by an
        # explicit owner_approval_condition. We still flag them for human review.
        for name, flag in (("external_send_permission", agent.external_send_permission),
                           ("deploy_permission", agent.deploy_permission),
                           ("scheduler_permission", agent.scheduler_permission),
                           ("secret_access", agent.secret_access)):
            if flag:
                self._issues.append(ValidationIssue(
                    Severity.STOP.value, self._relpath(), name,
                    "agent holds an elevated permission (Phase A requires default deny)",
                    entity_id=agent.id))

    def _relpath(self) -> str:
        try:
            return os.path.relpath(self.path, self.repo_root)
        except ValueError:
            return self.path

    # ── reference integrity ───────────────────────────────────
    def validate_references(self, skill_registry: SkillRegistry) -> List[ValidationIssue]:
        """Ensure every agent.skills entry exists in the skill registry."""
        self._ensure_loaded()
        issues: List[ValidationIssue] = []
        for agent in self._agents.values():
            for skill_id in agent.skills:
                if not skill_registry.has(skill_id):
                    issues.append(ValidationIssue(
                        Severity.FIX.value, self._relpath(), "skills",
                        f"references unknown skill '{skill_id}'", entity_id=agent.id))
        return issues

    # ── queries ───────────────────────────────────────────────
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    @property
    def load_error(self) -> Optional[str]:
        self._ensure_loaded()
        return self._load_error

    def issues(self) -> List[ValidationIssue]:
        self._ensure_loaded()
        return list(self._issues)

    def all_agents(self) -> List[AgentDefinition]:
        self._ensure_loaded()
        return list(self._agents.values())

    def get_agent(self, agent_id: str) -> Optional[AgentDefinition]:
        self._ensure_loaded()
        return self._agents.get(agent_id)

    def has(self, agent_id: str) -> bool:
        self._ensure_loaded()
        return agent_id in self._agents

    def resolve(self, agent_id: str, business: Optional[str] = None) -> RegistryResult:
        """Resolve an agent id to an actionable status (fails safe)."""
        self._ensure_loaded()

        if self._load_error:
            return RegistryResult(AgentStatus.INVALID_CONFIG.value, agent_id,
                                  reason=self._load_error)
        if agent_id in self._duplicate_ids:
            return RegistryResult(AgentStatus.INVALID_CONFIG.value, agent_id,
                                  reason="duplicate agent id")
        agent = self._agents.get(agent_id)
        if agent is None:
            return RegistryResult(AgentStatus.NOT_FOUND.value, agent_id,
                                  reason="agent not registered")
        if not agent.active:
            return RegistryResult(AgentStatus.INACTIVE.value, agent_id,
                                  definition=agent, reason="agent is inactive")
        if not agent.applies_to(business):
            return RegistryResult(AgentStatus.FORBIDDEN.value, agent_id,
                                  definition=agent,
                                  reason=f"agent not applicable to business '{business}'")
        if agent.owner_approval_conditions:
            return RegistryResult(AgentStatus.OWNER_APPROVAL_REQUIRED.value, agent_id,
                                  definition=agent,
                                  reason="agent has owner-approval conditions")
        return RegistryResult(AgentStatus.ALLOWED.value, agent_id,
                              definition=agent, reason="active, in scope")


def load_default() -> AgentRegistry:
    return AgentRegistry().load()
