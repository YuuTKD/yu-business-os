"""YU Business OS 2.0 — Business Config SSOT (Phase B1, shadow mode).

Read-only single source of truth for business configuration. NOT a production
read source yet: it loads and validates a registry, statically reads legacy
config (no import/exec), and compares them. No external I/O, no secrets.
"""

from .models import (
    ApprovalPolicy,
    AutomationPolicy,
    BusinessConfig,
    BusinessServiceConfig,
    ComparisonResult,
    ConfigDifference,
    LegacySource,
    LoaderStatus,
    MigrationStatus,
    NotificationPolicy,
    PostingPolicy,
    Status,
    ValidationResult,
)
from .loader import BusinessConfigRegistry, load_default
from .legacy_adapter import LegacyAdapter
from .comparator import compare

__all__ = [
    "BusinessConfigRegistry",
    "LegacyAdapter",
    "compare",
    "load_default",
    "BusinessConfig",
    "BusinessServiceConfig",
    "NotificationPolicy",
    "AutomationPolicy",
    "PostingPolicy",
    "ApprovalPolicy",
    "LegacySource",
    "ConfigDifference",
    "ComparisonResult",
    "ValidationResult",
    "Status",
    "MigrationStatus",
    "LoaderStatus",
]
