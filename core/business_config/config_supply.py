"""SSOT config supply decision for Batch-1 businesses (Phase B2-4).

Decides, per business, whether the runtime should receive an SSOT-derived
legacy-compatible config or fall back to legacy. Uses the existing comparator
for mismatch detection and the config builder for shape conversion. No external
I/O; fail-closed; secrets never read.

runtime_source: LEGACY | SSOT | FALLBACK_LEGACY
decision:       GO | FIX | STOP | OWNER_APPROVAL_REQUIRED | INTERNAL_ERROR
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from .config_builder import SUPPLIED_BUSINESSES, build_legacy_compatible_config

SUPPLY_SCOPE = set(SUPPLIED_BUSINESSES)
_OK_MIGRATION = {"SHADOW_DEFINED", "VERIFIED"}
_SSOT_MODES = {"SSOT_PRIMARY_WITH_LEGACY_FALLBACK", "AUTO", "OWNER_APPROVED"}


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _result(business_id, mode, **kw) -> Dict[str, Any]:
    base = {
        "business_id": business_id,
        "requested_mode": mode,
        "runtime_source": "LEGACY",
        "used_fallback": False,
        "fallback_reason": None,
        "owner_approved": kw.get("owner_approved", False),
        "config_shape_valid": None,
        "comparison_decision": None,
        "warnings": [],
        "decision": "GO",
        "config": None,
    }
    base.update({k: v for k, v in kw.items() if k in base})
    return base


def _legacy_config(business_id):
    from configs.business_registry import get as get_config
    try:
        return get_config(business_id)
    except ValueError:
        return None


def _resolve_canonical(business_id, root):
    """Resolve a legacy slug alias (e.g. 'hinabe') to its canonical id.

    Returns the canonical id, or the input unchanged if it is already canonical
    or unknown. Read-only; never raises.
    """
    try:
        from .loader import BusinessConfigRegistry
        canonical = BusinessConfigRegistry(repo_root=root).load().resolve_slug(business_id)
        return canonical or business_id
    except Exception:
        return business_id


def supply(business_id: str, mode: str = "LEGACY_ONLY", owner_approved: bool = False,
           repo_root: Optional[str] = None, registry=None) -> Dict[str, Any]:
    root = os.path.abspath(repo_root or _repo_root())
    mode = str(mode).strip().upper()

    # Resolve a legacy slug alias (e.g. 'hinabe' -> 'ryukyu_hinabe') so alias and
    # canonical requests yield the same config.
    legacy = _legacy_config(business_id)
    if legacy is None:
        canonical = _resolve_canonical(business_id, root)
        if canonical != business_id:
            business_id = canonical
            legacy = _legacy_config(business_id)

    r = _result(business_id, mode, owner_approved=owner_approved, config=legacy)

    try:
        if mode == "SSOT_ONLY":
            r["decision"] = "STOP"
            r["fallback_reason"] = "SSOT_ONLY_FORBIDDEN"
            return r
        if mode == "LEGACY_ONLY":
            r["decision"] = "GO"
            r["runtime_source"] = "LEGACY"
            return r
        if mode not in _SSOT_MODES:
            r["decision"] = "STOP"
            r["fallback_reason"] = "UNKNOWN_MODE"
            return r
        if business_id not in SUPPLY_SCOPE:
            r["decision"] = "GO"
            r["runtime_source"] = "LEGACY"
            r["warnings"].append("business_out_of_batch1")
            return r
        if legacy is None:
            r["decision"] = "STOP"
            r["fallback_reason"] = "UNKNOWN_BUSINESS"
            return r

        # Owner approval gate (AUTO needs the approval flag; OWNER_APPROVED implies it).
        approved = owner_approved if mode == "AUTO" else (owner_approved or mode == "OWNER_APPROVED")
        r["owner_approved"] = approved
        if not approved:
            r["decision"] = "GO"
            r["runtime_source"] = "LEGACY"
            r["warnings"].append("ssot_needs_owner_approval")
            return r

        # Load SSOT registry.
        from .loader import BusinessConfigRegistry
        registry = registry or BusinessConfigRegistry(repo_root=root).load()
        if registry.load_error:
            return _fallback(r, "SSOT_LOAD_FAILED")
        ssot = registry.get_business(business_id)
        if ssot is None:
            return _fallback(r, "SSOT_MISSING")
        if ssot.migration_status not in _OK_MIGRATION:
            r["decision"] = "STOP"
            r["fallback_reason"] = "SSOT_MIGRATION_NOT_ALLOWED"
            return r

        # Per-business comparison (reuse the existing comparator).
        from .comparator import compare
        from .legacy_adapter import LegacyAdapter
        cmp = compare(registry, LegacyAdapter(repo_root=root))
        per_biz = [d for d in cmp.differences if d.business in (business_id, ssot.slug)]
        dangerous = any(d.severity == "STOP" for d in per_biz)
        r["comparison_decision"] = "STOP" if dangerous else ("FIX" if per_biz else "GO")

        if dangerous:
            r["decision"] = "STOP"
            r["warnings"].extend(d.line() for d in per_biz if d.severity == "STOP")
            return r
        if per_biz:
            # A mismatch is reported (FIX), not hidden; supply legacy.
            r["decision"] = "FIX"
            r["runtime_source"] = "FALLBACK_LEGACY"
            r["used_fallback"] = True
            r["fallback_reason"] = "SSOT_LEGACY_MISMATCH"
            r["warnings"].extend(d.line() for d in per_biz)
            return r

        # Mismatch 0 → build the legacy-compatible config from SSOT.
        build = build_legacy_compatible_config(business_id, ssot, legacy)
        r["config_shape_valid"] = build.decision == "GO"
        if build.decision == "STOP":
            r["decision"] = "STOP"
            r["fallback_reason"] = build.reason
            r["warnings"].extend(build.issues)
            return r
        if build.decision == "FIX":
            r["decision"] = "FIX"
            r["runtime_source"] = "FALLBACK_LEGACY"
            r["used_fallback"] = True
            r["fallback_reason"] = build.reason
            r["warnings"].extend(build.issues)
            return r

        # GO → supply the SSOT-derived config.
        r["decision"] = "GO"
        r["runtime_source"] = "SSOT"
        r["config"] = build.config
        return r
    except Exception as exc:  # fail closed
        r["decision"] = "INTERNAL_ERROR"
        r["runtime_source"] = "FALLBACK_LEGACY"
        r["used_fallback"] = True
        r["fallback_reason"] = f"INTERNAL_ERROR:{type(exc).__name__}"
        r["config"] = legacy
        return r


def _fallback(r: Dict[str, Any], reason: str) -> Dict[str, Any]:
    r["decision"] = "GO"
    r["runtime_source"] = "FALLBACK_LEGACY"
    r["used_fallback"] = True
    r["fallback_reason"] = reason
    return r


def supply_batch(business_ids: List[str], mode="LEGACY_ONLY", owner_approved=False,
                 repo_root=None, registry=None) -> Dict[str, Any]:
    """Supply for several businesses. One STOP → batch STOP; else FIX if any FIX.
    Each business result is independent (no cross-write)."""
    results = {}
    for bid in business_ids:
        results[bid] = supply(bid, mode=mode, owner_approved=owner_approved,
                               repo_root=repo_root, registry=registry)
    decisions = [res["decision"] for res in results.values()]
    if "STOP" in decisions:
        batch = "STOP"
    elif "INTERNAL_ERROR" in decisions:
        batch = "INTERNAL_ERROR"
    elif "FIX" in decisions:
        batch = "FIX"
    else:
        batch = "GO"
    return {"batch_decision": batch, "results": results}
