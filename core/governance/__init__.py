"""YU Business OS 2.0 — Governance layer (Phase A).

Machine-judgeable GO / FIX / STOP / OWNER_APPROVAL_REQUIRED decisions over the
skill and agent registries. No external I/O; reasoning only.
"""

from .validator import (
    GovernanceRequest,
    GovernanceValidator,
    load_default,
)

__all__ = ["GovernanceValidator", "GovernanceRequest", "load_default"]
