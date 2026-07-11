"""Typed models + schema constants for the Business Config SSOT (Phase B1).

Standard library only (dataclasses + enum). The registry is **shadow mode**:
readable and comparable against legacy config, but never a production read
source. Secret / token / API-key VALUES are forbidden here — only environment
variable NAMES are stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────

class Status(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    PLANNED = "PLANNED"
    EXCLUDED = "EXCLUDED"
    ARCHIVED = "ARCHIVED"


class MigrationStatus(str, Enum):
    LEGACY_ONLY = "LEGACY_ONLY"
    SHADOW_DEFINED = "SHADOW_DEFINED"
    VERIFIED = "VERIFIED"
    READY_FOR_ADAPTER = "READY_FOR_ADAPTER"
    PARTIALLY_CONNECTED = "PARTIALLY_CONNECTED"
    PRODUCTION_CONNECTED = "PRODUCTION_CONNECTED"  # forbidden in Phase B1 data


class LoaderStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"
    NOT_FOUND = "NOT_FOUND"
    INVALID_CONFIG = "INVALID_CONFIG"
    LEGACY_ONLY = "LEGACY_ONLY"
    SHADOW_DEFINED = "SHADOW_DEFINED"
    VERIFIED = "VERIFIED"


# Phase B1 allows only these migration states in data. PRODUCTION_CONNECTED and
# any "connected" state are rejected (shadow mode must not claim production).
ALLOWED_MIGRATION = {
    MigrationStatus.LEGACY_ONLY.value,
    MigrationStatus.SHADOW_DEFINED.value,
    MigrationStatus.VERIFIED.value,
}
FORBIDDEN_MIGRATION = {
    MigrationStatus.PRODUCTION_CONNECTED.value,
    MigrationStatus.PARTIALLY_CONNECTED.value,
    MigrationStatus.READY_FOR_ADAPTER.value,
}
ALLOWED_STATUS = {s.value for s in Status}

REQUIRED_FIELDS = ("id", "slug", "display_name", "business_type", "status",
                   "migration_status")

# Field names that must never appear (would imply a secret value is stored).
FORBIDDEN_FIELD_NAMES = {
    "token", "api_key", "apikey", "secret", "password", "passwd",
    "private_key", "client_secret", "credentials", "access_token",
    "refresh_token", "bearer",
}


# ─────────────────────────────────────────────────────────────
# Sub-policies
# ─────────────────────────────────────────────────────────────

@dataclass
class BusinessServiceConfig:
    cloud_run_service: Optional[str] = None
    scheduler_jobs: List[str] = field(default_factory=list)
    line: Any = None
    threads: Any = None
    instagram: Any = None
    google_business_profile: Any = None
    gcs: Any = None
    sheets: Any = None
    drive: Any = None
    pos: Any = None

    @classmethod
    def from_dict(cls, d: Optional[Dict[str, Any]]) -> "BusinessServiceConfig":
        d = d or {}
        return cls(
            cloud_run_service=d.get("cloud_run_service"),
            scheduler_jobs=_as_list(d.get("scheduler_jobs")),
            line=d.get("line"), threads=d.get("threads"),
            instagram=d.get("instagram"),
            google_business_profile=d.get("google_business_profile"),
            gcs=d.get("gcs"), sheets=d.get("sheets"), drive=d.get("drive"),
            pos=d.get("pos"),
        )


@dataclass
class NotificationPolicy:
    mode: Any = None
    owner_channel_env: Optional[str] = None
    staff_channel_env: Optional[str] = None

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(mode=d.get("mode"),
                   owner_channel_env=d.get("owner_channel_env"),
                   staff_channel_env=d.get("staff_channel_env"))


@dataclass
class AutomationPolicy:
    scheduler_status: Any = None    # UNKNOWN by default (do not claim prod state)
    dry_run_default: Any = None

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(scheduler_status=d.get("scheduler_status"),
                   dry_run_default=d.get("dry_run_default"))


@dataclass
class PostingPolicy:
    platforms: List[str] = field(default_factory=list)
    daily_post_limit: Any = None     # frozen/protected — never store real value
    posting_window: Any = None

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(platforms=_as_list(d.get("platforms")),
                   daily_post_limit=d.get("daily_post_limit"),
                   posting_window=d.get("posting_window"))


@dataclass
class ApprovalPolicy:
    high_risk_requires_owner: bool = True

    @classmethod
    def from_dict(cls, d):
        d = d or {}
        return cls(high_risk_requires_owner=bool(d.get("high_risk_requires_owner", True)))


# ─────────────────────────────────────────────────────────────
# Business config
# ─────────────────────────────────────────────────────────────

@dataclass
class BusinessConfig:
    id: str
    slug: str = ""
    display_name: str = ""
    brand_name: str = ""
    business_type: str = ""
    status: str = Status.INACTIVE.value
    active: bool = False
    timezone: str = ""
    currency: str = ""
    owner: str = ""
    monthly_target: Any = None
    services: BusinessServiceConfig = field(default_factory=BusinessServiceConfig)
    notification_policy: NotificationPolicy = field(default_factory=NotificationPolicy)
    automation_policy: AutomationPolicy = field(default_factory=AutomationPolicy)
    posting_policy: PostingPolicy = field(default_factory=PostingPolicy)
    approval_policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    protected_fields: List[str] = field(default_factory=list)
    environment_variable_names: List[str] = field(default_factory=list)
    legacy_sources: List[str] = field(default_factory=list)
    migration_status: str = MigrationStatus.SHADOW_DEFINED.value
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BusinessConfig":
        return cls(
            id=str(d.get("id", "")).strip(),
            slug=str(d.get("slug", "") or d.get("id", "")).strip(),
            display_name=str(d.get("display_name", "")),
            brand_name=str(d.get("brand_name", "") or d.get("legal_or_brand_name", "")),
            business_type=str(d.get("business_type", "")),
            status=str(d.get("status", Status.INACTIVE.value)),
            active=bool(d.get("active", False)),
            timezone=str(d.get("timezone", "")),
            currency=str(d.get("currency", "")),
            owner=str(d.get("owner", "")),
            monthly_target=d.get("monthly_target"),
            services=BusinessServiceConfig.from_dict(d.get("services")),
            notification_policy=NotificationPolicy.from_dict(d.get("notification_policy")),
            automation_policy=AutomationPolicy.from_dict(d.get("automation_policy")),
            posting_policy=PostingPolicy.from_dict(d.get("posting_policy")),
            approval_policy=ApprovalPolicy.from_dict(d.get("approval_policy")),
            protected_fields=_as_list(d.get("protected_fields")),
            environment_variable_names=_as_list(d.get("environment_variable_names")),
            legacy_sources=_as_list(d.get("legacy_sources")),
            migration_status=str(d.get("migration_status", MigrationStatus.SHADOW_DEFINED.value)),
            metadata=d.get("metadata") if isinstance(d.get("metadata"), dict) else {},
            raw=d,
        )


# ─────────────────────────────────────────────────────────────
# Comparison / validation results
# ─────────────────────────────────────────────────────────────

@dataclass
class LegacySource:
    name: str
    businesses: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ConfigDifference:
    kind: str           # e.g. value_mismatch, legacy_only, registry_only, ...
    business: str
    field: str
    detail: str
    severity: str       # INFO | FIX | STOP

    def line(self) -> str:
        return f"[{self.severity}] {self.business}::{self.field} {self.kind} — {self.detail}"


@dataclass
class ComparisonResult:
    decision: str
    differences: List[ConfigDifference] = field(default_factory=list)

    def by_severity(self, sev: str) -> List[ConfigDifference]:
        return [d for d in self.differences if d.severity == sev]


@dataclass
class ValidationResult:
    decision: str
    issues: List[ConfigDifference] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]
