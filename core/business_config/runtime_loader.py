"""Runtime config loader — feature-flagged main-path connection (Phase B2-3).

Connects the production main path (entrypoint) to the SSOT runtime resolver
**behind a feature flag that defaults to LEGACY_ONLY**. In the default mode the
resolver is not even consulted and the legacy config object is returned
unchanged — zero behaviour change.

Feature flag: env ``YU_CONFIG_RUNTIME_MODE``
    LEGACY_ONLY   (default) legacy only; resolver not called
    AUTO                    resolver consulted; SSOT only if owner-approved
    OWNER_APPROVED          resolver consulted with owner approval

Owner approval: env ``YU_OWNER_APPROVED=true`` (one-shot; not persisted here).

Safety:
    * TACHINOMIYA is the only business in scope; others always stay LEGACY.
    * ``apply_runtime_config`` returns the legacy config object **unchanged**
      (production shape preserved). Phase B2-3 connects + decides + logs; it
      does not replace the concrete config values. It never raises (fail-closed
      to legacy) and never reads/logs token or secret VALUES.
    * No external network. The resolver is imported lazily so the default path
      stays dependency-light.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

LEGACY_ONLY = "LEGACY_ONLY"
AUTO = "AUTO"
OWNER_APPROVED = "OWNER_APPROVED"
_KNOWN_FLAGS = {LEGACY_ONLY, AUTO, OWNER_APPROVED}

FLAG_ENV = "YU_CONFIG_RUNTIME_MODE"
APPROVAL_ENV = "YU_OWNER_APPROVED"
IN_SCOPE = "tachinomiya"


def get_flag() -> str:
    val = (os.getenv(FLAG_ENV, "") or "").strip().upper()
    return val if val in _KNOWN_FLAGS else LEGACY_ONLY


def is_owner_approved() -> bool:
    return (os.getenv(APPROVAL_ENV, "") or "").strip().lower() == "true"


def resolve_source(business_name: str, repo_root: Optional[str] = None,
                   flag: Optional[str] = None,
                   owner_approved: Optional[bool] = None) -> Dict[str, Any]:
    """Decide the config source for ``business_name`` under the feature flag.

    Returns a structured, secret-safe decision. Fails closed to LEGACY on any
    problem. Only TACHINOMIYA may reach SSOT; everything else stays LEGACY.
    """
    flag = (flag or get_flag()).strip().upper()
    approved = is_owner_approved() if owner_approved is None else owner_approved
    result: Dict[str, Any] = {
        "business": business_name,
        "flag": flag if flag in _KNOWN_FLAGS else LEGACY_ONLY,
        "source": "LEGACY",
        "decision": "GO",
        "fallback_used": False,
        "reason": None,
        "mismatch_count": 0,
        "approval_state": "APPROVED" if approved else "NOT_APPROVED",
    }

    if flag not in _KNOWN_FLAGS:
        result["reason"] = "unknown_flag_default_legacy"
        return result
    if flag == LEGACY_ONLY:
        result["reason"] = "flag_legacy_only"
        return result
    if business_name != IN_SCOPE:
        result["reason"] = "business_out_of_scope"
        return result

    # AUTO / OWNER_APPROVED → consult the resolver (fail-closed to legacy).
    try:
        from .runtime_resolver import resolve, RuntimeMode
    except Exception as exc:  # pragma: no cover
        result["reason"] = f"resolver_unavailable:{type(exc).__name__}"
        return result

    mode = RuntimeMode.SSOT_PRIMARY_WITH_LEGACY_FALLBACK.value
    resolver_approved = approved if flag == AUTO else True
    try:
        res = resolve(business_id=IN_SCOPE, mode=mode,
                      owner_approved=resolver_approved, repo_root=repo_root)
    except Exception as exc:  # pragma: no cover
        result["reason"] = f"resolver_error:{type(exc).__name__}"
        return result

    result["decision"] = res["decision"]
    result["mismatch_count"] = res["mismatch_count"]
    result["fallback_used"] = res["fallback_used"]
    if res["runtime_source"] == "SSOT" and res["decision"] == "GO":
        result["source"] = "SSOT"
        result["reason"] = "ssot_primary_verified"
    else:
        result["source"] = "LEGACY"
        result["reason"] = res.get("fallback_reason") or res["decision"]
    return result


def apply_runtime_config(business_name: str, legacy_config: Any,
                         repo_root: Optional[str] = None,
                         emit_log: bool = True) -> Any:
    """Main-path hook. Returns the legacy config object **unchanged**.

    In LEGACY_ONLY (default) it is a pass-through. In AUTO/OWNER_APPROVED it
    additionally records which source the resolver would use (SSOT is verified
    equal to legacy when chosen). It never changes the returned object's shape
    or values, and never raises.
    """
    try:
        decision = resolve_source(business_name, repo_root=repo_root)
        if emit_log:
            print(
                "[runtime_config] "
                f"business={decision['business']} flag={decision['flag']} "
                f"source={decision['source']} decision={decision['decision']} "
                f"fallback={decision['fallback_used']} reason={decision['reason']}"
            )
    except Exception as exc:  # fail closed — never break the main path
        print(f"[runtime_config] fail-closed to LEGACY ({type(exc).__name__})")
    return legacy_config


def runtime_decision(business_name: str, repo_root: Optional[str] = None) -> Dict[str, Any]:
    """Return the structured decision without touching the config (for CLI/tests)."""
    return resolve_source(business_name, repo_root=repo_root)
