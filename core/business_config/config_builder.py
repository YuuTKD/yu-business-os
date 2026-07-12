"""Legacy-compatible config builder from the SSOT (Phase B2-4, Batch 1).

Converts an SSOT ``BusinessConfig`` into a dict that matches the shape the
existing runtime expects (the ``configs/business_registry.py`` entry shape) for
the Batch-1 businesses: TACHINOMIYA, TREE'S CATERING, TREE BEAUTY.

Design:
    * The SSOT owns a small set of scalar fields (monthly_target, business_type,
      status, cloud_run_service). Those are overlaid onto a **deep copy** of the
      legacy dict; every other key (menu_map, content_themes, line_channels,
      email, pos folders, …) passes through from legacy unchanged.
    * LINE env NAMES are NOT overlaid — the real Cloud Run env is keyed by the
      legacy name, so changing it would be a production switch (forbidden).
    * The input legacy dict is never mutated; a new dict is returned.
    * Secret VALUES are never read. Only names / non-secret scalars are touched.
    * On any missing/typed-wrong SSOT field or shape problem the build reports
      FIX (caller falls back to legacy); cross-business identity errors → STOP.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .models import BusinessConfig, Status

# Businesses whose config the SSOT may supply (SSOT ids).
BATCH1_BUSINESSES = ("tachinomiya", "catering", "beauty")
BATCH2_BUSINESSES = ("ryukyu_hinabe",)          # Batch 2: 火鍋 only (pasta_pasta / z1 out of scope)
SUPPLIED_BUSINESSES = BATCH1_BUSINESSES + BATCH2_BUSINESSES


@dataclass
class BuildResult:
    business_id: str
    decision: str                    # GO | FIX | STOP
    source: str                      # SSOT | FALLBACK_LEGACY
    config: Optional[Dict[str, Any]] = None
    issues: List[str] = field(default_factory=list)
    reason: Optional[str] = None


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def build_legacy_compatible_config(business_id: str, ssot: Optional[BusinessConfig],
                                   legacy: Optional[Dict[str, Any]]) -> BuildResult:
    """Build a legacy-shaped config for ``business_id`` from the SSOT.

    Never mutates ``legacy``; returns a new dict on GO.
    """
    if business_id not in SUPPLIED_BUSINESSES:
        return BuildResult(business_id, "STOP", "FALLBACK_LEGACY",
                           reason="business_out_of_scope",
                           issues=[f"{business_id} is not a supplied business"])
    if ssot is None:
        return BuildResult(business_id, "FIX", "FALLBACK_LEGACY",
                           reason="ssot_missing", issues=["SSOT config missing"])
    if not isinstance(legacy, dict) or not legacy:
        return BuildResult(business_id, "FIX", "FALLBACK_LEGACY",
                           reason="legacy_missing", issues=["legacy config missing"])

    # Cross-business identity: SSOT id/slug must match the requested business.
    if ssot.id != business_id and ssot.slug != business_id:
        return BuildResult(business_id, "STOP", "FALLBACK_LEGACY",
                           reason="cross_business_contamination",
                           issues=[f"SSOT id/slug {ssot.id!r}/{ssot.slug!r} != {business_id!r}"])

    issues: List[str] = []

    # Validate the SSOT-owned scalar fields (missing / wrong type → FIX).
    if not _is_int(ssot.monthly_target):
        issues.append("monthly_target missing or not int")
    if not (isinstance(ssot.business_type, str) and ssot.business_type):
        issues.append("business_type missing")
    if not (isinstance(ssot.services.cloud_run_service, str)
            and ssot.services.cloud_run_service):
        issues.append("cloud_run_service missing")
    if ssot.status not in {s.value for s in Status}:
        issues.append(f"unknown status {ssot.status!r}")

    if issues:
        return BuildResult(business_id, "FIX", "FALLBACK_LEGACY",
                           reason="ssot_field_invalid", issues=issues)

    # Build: deep copy legacy, overlay only the verified SSOT-owned scalars.
    built = copy.deepcopy(legacy)
    built["monthly_target"] = ssot.monthly_target
    built["business_type"] = ssot.business_type
    built["cloud_run_service"] = ssot.services.cloud_run_service
    # SSOT ACTIVE + active flag → legacy "active"; otherwise keep legacy status.
    if ssot.status == Status.ACTIVE.value and ssot.active:
        built["status"] = "active"

    # Shape validation: built must retain every legacy key with matching types.
    ok, missing, type_mm = validate_legacy_shape(built, legacy)
    if not ok:
        return BuildResult(business_id, "FIX", "FALLBACK_LEGACY",
                           reason="shape_invalid",
                           issues=[f"missing={missing}", f"type_mismatch={type_mm}"])

    return BuildResult(business_id, "GO", "SSOT", config=built)


def validate_legacy_shape(built: Dict[str, Any], legacy: Dict[str, Any]):
    """Return (ok, missing_keys, type_mismatches) comparing built vs legacy."""
    missing = [k for k in legacy if k not in built]
    type_mm = [k for k in legacy
               if k in built and type(built[k]) is not type(legacy[k])]
    return (not missing and not type_mm, missing, type_mm)


def compare_runtime_shape(built: Dict[str, Any], legacy: Dict[str, Any]) -> List[str]:
    """List keys whose value differs between built and legacy (names only)."""
    diffs = []
    for k in legacy:
        if k in built and built[k] != legacy[k]:
            diffs.append(k)
    return diffs


# ── per-business convenience wrappers (data-driven; no duplicated logic) ──
def _build_for(business_id: str, repo_root=None) -> BuildResult:
    from .loader import BusinessConfigRegistry
    from configs.business_registry import get as get_config
    reg = BusinessConfigRegistry(repo_root=repo_root).load()
    ssot = reg.get_business(business_id)
    try:
        legacy = get_config(business_id)
    except ValueError:
        legacy = None
    return build_legacy_compatible_config(business_id, ssot, legacy)


def build_tachinomiya_config(repo_root=None) -> BuildResult:
    return _build_for("tachinomiya", repo_root)


def build_trees_catering_config(repo_root=None) -> BuildResult:
    return _build_for("catering", repo_root)


def build_tree_beauty_config(repo_root=None) -> BuildResult:
    return _build_for("beauty", repo_root)


def build_ryukyu_hinabe_config(repo_root=None) -> BuildResult:
    return _build_for("ryukyu_hinabe", repo_root)
