"""TACHINOMIYA Runtime Config Resolver (Phase B2-2).

Chooses the config source for TACHINOMIYA at runtime:

    LEGACY_ONLY                        always legacy
    SHADOW_ONLY                        legacy value, compared against SSOT
    SSOT_PRIMARY_WITH_LEGACY_FALLBACK  SSOT when it is clean & matches, else
                                       fall back to legacy (infra/schema issues
                                       only — a mismatch is never hidden by
                                       fallback; it is FIX/STOP)
    SSOT_ONLY                          FORBIDDEN in Phase B2-2 → STOP

Only ``tachinomiya`` may use an SSOT-primary mode. Any other business requesting
it is a STOP; other businesses always resolve to LEGACY.

Guarantees:
    * SSOT is returned only when: approved + mismatch 0 + no dangerous issue +
      migration_status in {SHADOW_DEFINED, VERIFIED}
    * a mismatch NEVER silently falls back — it is FIX (non-dangerous) or STOP
    * env NAMES only; token / secret VALUES are never read, compared or logged
    * no import side effects, no external network; fail-closed on any error
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from .loader import BusinessConfigRegistry
from .shadow_adapter import compare_tachinomiya, _load_legacy, BUSINESS_ID


class RuntimeMode(str, Enum):
    LEGACY_ONLY = "LEGACY_ONLY"
    SHADOW_ONLY = "SHADOW_ONLY"
    SSOT_PRIMARY_WITH_LEGACY_FALLBACK = "SSOT_PRIMARY_WITH_LEGACY_FALLBACK"
    SSOT_ONLY = "SSOT_ONLY"  # forbidden in Phase B2-2


_ALLOWED_MODES = {
    RuntimeMode.LEGACY_ONLY.value,
    RuntimeMode.SHADOW_ONLY.value,
    RuntimeMode.SSOT_PRIMARY_WITH_LEGACY_FALLBACK.value,
}
_SSOT_MODES = {RuntimeMode.SSOT_PRIMARY_WITH_LEGACY_FALLBACK.value,
               RuntimeMode.SSOT_ONLY.value}
_OK_MIGRATION = {"SHADOW_DEFINED", "VERIFIED"}


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base(business_id, mode_val, correlation_id, approved) -> Dict[str, Any]:
    return {
        "business_id": business_id,
        "mode": mode_val,
        "decision": "INTERNAL_ERROR",
        "runtime_source": "LEGACY",   # invariant unless SSOT is explicitly chosen
        "fallback_used": False,
        "fallback_reason": None,
        "mismatch_count": 0,
        "approval_state": "APPROVED" if approved else "NOT_APPROVED",
        "timestamp": _now(),
        "correlation_id": correlation_id or uuid.uuid4().hex,
        "config": None,
    }


def resolve(
    business_id: str = BUSINESS_ID,
    mode: str = RuntimeMode.LEGACY_ONLY.value,
    owner_approved: bool = False,
    registry: Optional[BusinessConfigRegistry] = None,
    legacy_override: Optional[Dict[str, Any]] = None,
    repo_root: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    root = os.path.abspath(repo_root or _repo_root())
    mode_val = str(mode).strip().upper()
    r = _base(business_id, mode_val, correlation_id, owner_approved)

    try:
        # SSOT_ONLY is forbidden this phase.
        if mode_val == RuntimeMode.SSOT_ONLY.value:
            r["decision"] = "STOP"
            r["fallback_reason"] = "SSOT_ONLY_FORBIDDEN"
            return r
        if mode_val not in _ALLOWED_MODES:
            r["decision"] = "STOP"
            r["fallback_reason"] = "UNKNOWN_MODE"
            return r

        # Only TACHINOMIYA may use SSOT-primary. Other businesses stay LEGACY.
        if business_id != BUSINESS_ID:
            if mode_val in _SSOT_MODES:
                r["decision"] = "STOP"
                r["fallback_reason"] = "OTHER_BUSINESS_SSOT_FORBIDDEN"
                return r
            r["decision"] = "GO"
            r["runtime_source"] = "LEGACY"
            return r

        registry = registry or BusinessConfigRegistry(repo_root=root).load()
        legacy = legacy_override if legacy_override is not None else _load_legacy(root)

        if mode_val == RuntimeMode.LEGACY_ONLY.value:
            r["decision"] = "GO"
            r["runtime_source"] = "LEGACY"
            r["config"] = legacy
            return r

        if mode_val == RuntimeMode.SHADOW_ONLY.value:
            shadow = compare_tachinomiya(mode="SHADOW_ONLY", registry=registry,
                                         legacy_override=legacy, repo_root=root,
                                         correlation_id=r["correlation_id"])
            r["mismatch_count"] = shadow["mismatch_count"]
            r["runtime_source"] = "LEGACY"
            r["config"] = legacy
            r["decision"] = shadow["decision"]   # GO / FIX / STOP
            return r

        # ── SSOT_PRIMARY_WITH_LEGACY_FALLBACK ──
        if not owner_approved:
            r["decision"] = "OWNER_APPROVAL_REQUIRED"
            r["runtime_source"] = "LEGACY"
            return r

        # 1. SSOT availability first — infra/schema issues fall back to legacy
        #    (a genuine SSOT-vs-legacy mismatch is handled below, never hidden).
        if registry.load_error:
            return _fallback(r, legacy, "SSOT_LOAD_FAILED")
        ssot = registry.get_business(BUSINESS_ID)
        if ssot is None:
            return _fallback(r, legacy, "SSOT_MISSING")

        # 2. Compare SSOT vs legacy (SSOT now known to exist).
        shadow = compare_tachinomiya(mode="SHADOW_ONLY", registry=registry,
                                     legacy_override=legacy, repo_root=root,
                                     correlation_id=r["correlation_id"])
        r["mismatch_count"] = shadow["mismatch_count"]
        dangerous = any(m["severity"] == "STOP" for m in shadow["mismatches"])

        if dangerous:                    # never resolved by fallback
            r["decision"] = "STOP"
            r["runtime_source"] = "LEGACY"
            r["config"] = legacy
            return r
        if r["mismatch_count"] > 0:      # must be fixed, not silently fallen back
            r["decision"] = "FIX"
            r["runtime_source"] = "LEGACY"
            r["config"] = legacy
            return r

        # 3. SSOT self-validity.
        val = registry.validate()
        if val.decision == "STOP":
            r["decision"] = "STOP"       # dangerous SSOT (secret/dup/etc.)
            r["runtime_source"] = "LEGACY"
            r["config"] = legacy
            return r
        if val.decision == "FIX":
            return _fallback(r, legacy, "SSOT_SCHEMA_INCOMPLETE")
        if ssot.migration_status not in _OK_MIGRATION:
            r["decision"] = "STOP"
            r["runtime_source"] = "LEGACY"
            r["fallback_reason"] = "SSOT_MIGRATION_NOT_ALLOWED"
            r["config"] = legacy
            return r

        # 4. All clear → SSOT is primary.
        r["decision"] = "GO"
        r["runtime_source"] = "SSOT"
        r["fallback_used"] = False
        r["config"] = ssot
        return r
    except Exception as exc:  # fail closed
        r["decision"] = "INTERNAL_ERROR"
        r["runtime_source"] = "LEGACY"
        r["fallback_reason"] = f"INTERNAL_ERROR:{type(exc).__name__}"
        return r


def _fallback(r: Dict[str, Any], legacy: Any, reason: str) -> Dict[str, Any]:
    r["decision"] = "GO_WITH_FALLBACK"
    r["runtime_source"] = "LEGACY"
    r["fallback_used"] = True
    r["fallback_reason"] = reason
    r["config"] = legacy
    return r


def resolve_tachinomiya(mode=RuntimeMode.LEGACY_ONLY.value, **kwargs) -> Dict[str, Any]:
    return resolve(business_id=BUSINESS_ID, mode=mode, **kwargs)
