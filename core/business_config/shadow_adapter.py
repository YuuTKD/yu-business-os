"""TACHINOMIYA SSOT Shadow Adapter (Phase B2-1).

Reads the Legacy config and the shadow SSOT for TACHINOMIYA, compares them at
runtime, and returns a structured decision. **The runtime source is always
LEGACY** — the SSOT value is never returned to production. This is a shadow
connection: it can be called, but it does not change what production reads.

Guarantees:
    * runtime_source is always "LEGACY" (enforced; SSOT would be a STOP)
    * env-var NAMES only are compared — never token/secret VALUES
    * legacy config is read statically (AST via legacy adapter helpers); no
      import side effects, no external network
    * fail-closed: unknown mode / missing config / any exception → STOP or
      INTERNAL_ERROR, never a silent GO
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from .loader import BusinessConfigRegistry
from .legacy_adapter import extract_dict_literal
from .comparator import _env_known

BUSINESS_ID = "tachinomiya"


class ShadowMode(str, Enum):
    OFF = "OFF"                       # do not read SSOT; legacy only
    SHADOW_ONLY = "SHADOW_ONLY"       # compare, record, continue on legacy
    ENFORCE_COMPARE = "ENFORCE_COMPARE"  # mismatch → STOP (still legacy value)


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_legacy(repo_root: str) -> Dict[str, Any]:
    """Statically read TACHINOMIYA from business_registry.py (no import)."""
    path = os.path.join(repo_root, "configs", "business_registry.py")
    raw = extract_dict_literal(path, "BUSINESSES")
    t = raw.get(BUSINESS_ID) or {}
    line_channels = t.get("line_channels") or {}
    staff = (line_channels.get("staff") or {}) if isinstance(line_channels, dict) else {}
    other_services = {
        k: (v.get("cloud_run_service") if isinstance(v, dict) else None)
        for k, v in raw.items() if k != BUSINESS_ID
    }
    return {
        "slug": BUSINESS_ID,
        "display_name": t.get("name"),
        "business_type": t.get("business_type"),
        "status": t.get("status"),
        "active": t.get("status") == "active",
        "monthly_target": t.get("monthly_target"),
        "cloud_run_service": t.get("cloud_run_service"),
        "spreadsheet_id_env": t.get("spreadsheet_id_env"),
        "line_staff_env": staff.get("env_key") if isinstance(staff, dict) else None,
        "platforms": t.get("platforms"),
        "timezone": None,  # not present in legacy
        "_other_services": {v for v in other_services.values() if v},
    }


def _mm(field: str, ssot: Any, legacy: Any, severity: str, note: str = "") -> Dict[str, Any]:
    # NOTE: only names / non-secret scalars are placed here.
    return {"field": field, "severity": severity, "ssot": ssot, "legacy": legacy, "note": note}


def _compare(ssot, legacy: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    # identity — mismatch here means cross-business contamination (STOP)
    if legacy.get("slug") not in (None, BUSINESS_ID) or ssot.slug != BUSINESS_ID:
        out.append(_mm("business_id", ssot.slug, legacy.get("slug"), "STOP",
                       "identity mismatch / cross-business contamination"))

    # display_name
    if legacy.get("display_name") and ssot.display_name != legacy["display_name"]:
        out.append(_mm("display_name", ssot.display_name, legacy["display_name"], "FIX"))

    # active
    if legacy.get("active") != ssot.active:
        out.append(_mm("active", ssot.active, legacy.get("active"), "FIX"))

    # monthly target total
    if legacy.get("monthly_target") is not None and \
            _num_ne(ssot.monthly_target, legacy["monthly_target"]):
        out.append(_mm("monthly_target_total", ssot.monthly_target,
                       legacy["monthly_target"], "FIX"))

    # day/night must sum to total (SSOT-internal, dangerous → STOP)
    d, n, t = ssot.monthly_target_day, ssot.monthly_target_night, ssot.monthly_target
    if d is not None and n is not None:
        try:
            if int(d) + int(n) != int(t):
                out.append(_mm("monthly_target_breakdown", f"{d}+{n}", t, "STOP",
                               "day+night != total"))
        except (TypeError, ValueError):
            out.append(_mm("monthly_target_breakdown", f"{d}+{n}", t, "STOP",
                           "non-integer breakdown"))

    # cloud_run_service — mismatch that matches another business = contamination
    ls = legacy.get("cloud_run_service")
    if ls and ssot.services.cloud_run_service != ls:
        if ls in legacy.get("_other_services", set()):
            out.append(_mm("cloud_run_service", ssot.services.cloud_run_service, ls,
                           "STOP", "value belongs to another business"))
        else:
            out.append(_mm("cloud_run_service", ssot.services.cloud_run_service, ls, "FIX"))

    # spreadsheet env NAME (via canonical/alias)
    se = legacy.get("spreadsheet_id_env")
    if se and not _env_known(ssot, se):
        out.append(_mm("spreadsheet_id_env", "(canonical set)", se, "FIX",
                       "legacy env name not tracked as canonical/alias"))

    # LINE owner canonical NAME
    if ssot.notification_policy.owner_channel_env != "LINE_OWNER_TOKEN":
        out.append(_mm("line_owner_env", ssot.notification_policy.owner_channel_env,
                       "LINE_OWNER_TOKEN", "FIX"))

    # LINE staff: legacy name must resolve to the canonical (alias allowed)
    staff_legacy = legacy.get("line_staff_env")
    canonical = ssot.notification_policy.staff_channel_env
    if staff_legacy:
        resolved_ok = (staff_legacy == canonical) or (
            ssot.environment_variable_aliases.get(staff_legacy) == canonical)
        if not resolved_ok:
            out.append(_mm("line_staff_env", canonical, staff_legacy, "FIX",
                           "legacy staff env not canonical/alias"))

    # posting platforms
    lp = legacy.get("platforms")
    if lp and set(ssot.posting_policy.platforms) != set(lp):
        out.append(_mm("posting_platforms", sorted(ssot.posting_policy.platforms),
                       sorted(lp), "FIX"))

    # migration must not claim production
    if ssot.migration_status == "PRODUCTION_CONNECTED":
        out.append(_mm("migration_status", ssot.migration_status, "-", "STOP",
                       "shadow mode must not claim production"))

    return out


def compare_tachinomiya(
    mode: str = ShadowMode.SHADOW_ONLY.value,
    registry: Optional[BusinessConfigRegistry] = None,
    legacy_override: Optional[Dict[str, Any]] = None,
    repo_root: Optional[str] = None,
    correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare SSOT vs Legacy for TACHINOMIYA. Returns a structured result.

    Never raises: any internal problem yields INTERNAL_ERROR (fail-closed).
    """
    root = os.path.abspath(repo_root or _repo_root())
    mode_val = str(mode).strip().upper()
    result: Dict[str, Any] = {
        "business_id": BUSINESS_ID,
        "mode": mode_val,
        "decision": "INTERNAL_ERROR",
        "legacy_source": "configs/business_registry.py::BUSINESSES",
        "ssot_source": "configs/businesses/registry.yaml",
        "mismatch_count": 0,
        "mismatches": [],
        "runtime_source": "LEGACY",   # invariant
        "timestamp": _now(),
        "correlation_id": correlation_id or uuid.uuid4().hex,
    }

    try:
        if mode_val not in {m.value for m in ShadowMode}:
            result["decision"] = "STOP"
            result["mismatches"] = [_mm("mode", mode_val, "-", "STOP", "unknown mode")]
            result["mismatch_count"] = 1
            return result

        if mode_val == ShadowMode.OFF.value:
            # Do not read the SSOT at all; legacy is authoritative.
            result["decision"] = "GO"
            result["ssot_source"] = "(not read: OFF)"
            return result

        registry = registry or BusinessConfigRegistry(repo_root=root).load()
        ssot = registry.get_business(BUSINESS_ID)
        legacy = legacy_override if legacy_override is not None else _load_legacy(root)

        if ssot is None or not legacy:
            result["decision"] = "INTERNAL_ERROR"
            result["mismatches"] = [_mm("config", "ssot" if ssot is None else "legacy",
                                        "-", "STOP", "config missing")]
            result["mismatch_count"] = 1
            return result

        mismatches = _compare(ssot, legacy)
        result["mismatches"] = mismatches
        result["mismatch_count"] = len(mismatches)

        dangerous = any(m["severity"] == "STOP" for m in mismatches)

        if result["runtime_source"] != "LEGACY":  # defensive invariant
            result["decision"] = "STOP"
        elif dangerous:
            result["decision"] = "STOP"
        elif not mismatches:
            result["decision"] = "GO"
        elif mode_val == ShadowMode.ENFORCE_COMPARE.value:
            result["decision"] = "STOP"
        else:  # SHADOW_ONLY with non-dangerous mismatches
            result["decision"] = "FIX"
        return result
    except Exception as exc:  # fail closed
        result["decision"] = "INTERNAL_ERROR"
        result["mismatches"] = [_mm("exception", type(exc).__name__, "-", "STOP", str(exc))]
        result["mismatch_count"] = 1
        return result


def shadow_check(business_id: str = BUSINESS_ID, mode: str = ShadowMode.OFF.value,
                 **kwargs) -> Dict[str, Any]:
    """Optional hook for production code. Defaults to OFF (no SSOT read, no
    behaviour change). Production is NOT wired to call this in Phase B2-1."""
    if business_id != BUSINESS_ID:
        return {"business_id": business_id, "decision": "GO", "runtime_source": "LEGACY",
                "mode": str(mode).upper(), "mismatch_count": 0, "mismatches": [],
                "note": "not in scope for Phase B2-1"}
    return compare_tachinomiya(mode=mode, **kwargs)


def _num_ne(a, b) -> bool:
    try:
        return float(a) != float(b)
    except (TypeError, ValueError):
        return a != b
