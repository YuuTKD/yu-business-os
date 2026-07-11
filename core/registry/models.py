"""Typed models for the YU Business OS 2.0 Registry & Governance layer.

Standard-library only (dataclasses + enum). PyYAML/pydantic are intentionally
NOT required so this layer runs anywhere with zero new dependencies.

Enums use ``str`` mixin so values compare/serialise as plain strings, which
keeps the CLI output and test assertions simple.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────

class SkillStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FALLBACK_DIRECT_MD = "FALLBACK_DIRECT_MD"
    FALLBACK_LOGIC = "FALLBACK_LOGIC"
    INACTIVE = "INACTIVE"
    NOT_FOUND = "NOT_FOUND"
    FORBIDDEN = "FORBIDDEN"
    INVALID_CONFIG = "INVALID_CONFIG"


class AgentStatus(str, Enum):
    ALLOWED = "ALLOWED"
    OWNER_APPROVAL_REQUIRED = "OWNER_APPROVAL_REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    INACTIVE = "INACTIVE"
    NOT_FOUND = "NOT_FOUND"
    INVALID_CONFIG = "INVALID_CONFIG"


class FallbackBehavior(str, Enum):
    DIRECT_SKILL_MD = "DIRECT_SKILL_MD"
    LOGIC_DIRECT_APPLY = "LOGIC_DIRECT_APPLY"
    INACTIVE = "INACTIVE"
    STOP = "STOP"


class Decision(str, Enum):
    """Governance decision. Ordered by severity for easy escalation."""
    GO = "GO"
    OWNER_APPROVAL_REQUIRED = "OWNER_APPROVAL_REQUIRED"
    FIX = "FIX"
    STOP = "STOP"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Severity(str, Enum):
    INFO = "INFO"
    FIX = "FIX"
    STOP = "STOP"


# ─────────────────────────────────────────────────────────────
# Permission model (shared shape; default deny)
# ─────────────────────────────────────────────────────────────

@dataclass
class PermissionSet:
    """Capability flags. Every flag defaults to ``False`` (default deny)."""
    read: bool = False
    write: bool = False
    external_send: bool = False
    deploy: bool = False
    scheduler: bool = False
    secret_access: bool = False

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PermissionSet":
        data = data or {}
        return cls(
            read=bool(data.get("read", False)),
            write=bool(data.get("write", False)),
            external_send=bool(data.get("external_send", False)),
            deploy=bool(data.get("deploy", False)),
            scheduler=bool(data.get("scheduler", False)),
            secret_access=bool(data.get("secret_access", False)),
        )


# ─────────────────────────────────────────────────────────────
# Definitions
# ─────────────────────────────────────────────────────────────

@dataclass
class SkillDefinition:
    id: str
    name: str = ""
    version: str = ""
    skill_md_path: str = ""
    description: str = ""
    triggers: List[str] = field(default_factory=list)
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    applicable_businesses: List[str] = field(default_factory=list)
    permissions: PermissionSet = field(default_factory=PermissionSet)
    prohibited_actions: List[str] = field(default_factory=list)
    fallback_behavior: str = FallbackBehavior.LOGIC_DIRECT_APPLY.value
    qa_criteria: List[str] = field(default_factory=list)
    owner_approval_required: bool = False
    active: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SkillDefinition":
        return cls(
            id=str(data.get("id", "")).strip(),
            name=str(data.get("name", "")),
            version=str(data.get("version", "")),
            skill_md_path=str(data.get("skill_md_path", "") or ""),
            description=str(data.get("description", "")),
            triggers=_as_list(data.get("triggers")),
            input_schema=_as_dict(data.get("input_schema")),
            output_schema=_as_dict(data.get("output_schema")),
            applicable_businesses=_as_list(data.get("applicable_businesses")),
            permissions=PermissionSet.from_dict(data.get("permissions")),
            prohibited_actions=_as_list(data.get("prohibited_actions")),
            fallback_behavior=str(data.get("fallback_behavior", FallbackBehavior.LOGIC_DIRECT_APPLY.value)),
            qa_criteria=_as_list(data.get("qa_criteria")),
            owner_approval_required=bool(data.get("owner_approval_required", False)),
            active=bool(data.get("active", False)),
        )

    def applies_to(self, business: Optional[str]) -> bool:
        if business is None:
            return True
        biz = {b.lower() for b in self.applicable_businesses}
        return "all" in biz or business.lower() in biz


@dataclass
class AgentDefinition:
    id: str
    name: str = ""
    role: str = ""
    description: str = ""
    applicable_businesses: List[str] = field(default_factory=list)
    read_permissions: List[str] = field(default_factory=list)
    write_permissions: List[str] = field(default_factory=list)
    external_send_permission: bool = False
    deploy_permission: bool = False
    scheduler_permission: bool = False
    secret_access: bool = False
    owner_approval_conditions: List[str] = field(default_factory=list)
    stop_conditions: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    kpis: List[str] = field(default_factory=list)
    active: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentDefinition":
        return cls(
            id=str(data.get("id", "")).strip(),
            name=str(data.get("name", "")),
            role=str(data.get("role", "")),
            description=str(data.get("description", "")),
            applicable_businesses=_as_list(data.get("applicable_businesses")),
            read_permissions=_as_list(data.get("read_permissions")),
            write_permissions=_as_list(data.get("write_permissions")),
            external_send_permission=bool(data.get("external_send_permission", False)),
            deploy_permission=bool(data.get("deploy_permission", False)),
            scheduler_permission=bool(data.get("scheduler_permission", False)),
            secret_access=bool(data.get("secret_access", False)),
            owner_approval_conditions=_as_list(data.get("owner_approval_conditions")),
            stop_conditions=_as_list(data.get("stop_conditions")),
            skills=_as_list(data.get("skills")),
            inputs=_as_list(data.get("inputs")),
            outputs=_as_list(data.get("outputs")),
            logs=_as_list(data.get("logs")),
            kpis=_as_list(data.get("kpis")),
            active=bool(data.get("active", False)),
        )

    def applies_to(self, business: Optional[str]) -> bool:
        if business is None:
            return True
        biz = {b.lower() for b in self.applicable_businesses}
        return "all" in biz or business.lower() in biz


# ─────────────────────────────────────────────────────────────
# Results
# ─────────────────────────────────────────────────────────────

@dataclass
class RegistryResult:
    """Result of resolving a skill or agent id."""
    status: str
    entity_id: str
    definition: Optional[Any] = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (SkillStatus.AVAILABLE.value, AgentStatus.ALLOWED.value)


@dataclass
class ValidationIssue:
    severity: str
    file: str
    field: str
    reason: str
    entity_id: str = ""

    def line(self) -> str:
        loc = f"{self.file}::{self.entity_id}::{self.field}" if self.entity_id else f"{self.file}::{self.field}"
        return f"[{self.severity}] {loc} — {self.reason}"


@dataclass
class GovernanceResult:
    decision: str
    reasons: List[str] = field(default_factory=list)
    matched_policies: List[str] = field(default_factory=list)
    risk_level: str = RiskLevel.LOW.value


# ─────────────────────────────────────────────────────────────
# Coercion helpers
# ─────────────────────────────────────────────────────────────

def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}
