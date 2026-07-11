"""Compare the shadow Business Config Registry against legacy sources (Phase B1).

Read-only. Produces a ComparisonResult with a GO / FIX / STOP decision:

    GO   registry matches the authoritative legacy source; no dangerous issue
    FIX  non-dangerous divergence (value/enum/subset/missing) — report, do not
         auto-overwrite
    STOP secret value, cross-business contamination, duplicate id/slug, or a
         config claiming production connection

The comparator never overwrites legacy config and never reads secret values.
"""

from __future__ import annotations

from typing import Dict, List

from .loader import BusinessConfigRegistry
from .legacy_adapter import LegacyAdapter
from .models import ComparisonResult, ConfigDifference


def _decision(diffs: List[ConfigDifference]) -> str:
    if any(d.severity == "STOP" for d in diffs):
        return "STOP"
    if any(d.severity == "FIX" for d in diffs):
        return "FIX"
    return "GO"


def compare(registry: BusinessConfigRegistry, adapter: LegacyAdapter) -> ComparisonResult:
    diffs: List[ConfigDifference] = []

    # Registry-internal issues (secret / dup / bad enum) carry over first.
    reg_val = registry.validate()
    diffs.extend(reg_val.issues)

    reg_by_slug = {b.slug: b for b in registry.list_businesses()}

    # ── cross-business contamination (registry side) ──────────
    for field_name in ("cloud_run_service", "spreadsheet_id_env"):
        seen: Dict[str, str] = {}
        for slug, b in reg_by_slug.items():
            if field_name == "cloud_run_service":
                val = b.services.cloud_run_service
            else:
                val = _first_spreadsheet_env(b)
            if not val:
                continue
            if val in seen:
                diffs.append(ConfigDifference(
                    "cross_business_contamination", slug, field_name,
                    f"'{val}' also used by '{seen[val]}'", "STOP"))
            else:
                seen[val] = slug

    # ── registry ↔ business_registry.py (authoritative) ───────
    breg = adapter.business_registry()
    if breg.error:
        diffs.append(ConfigDifference("legacy_unreadable", "*",
                     "business_registry", breg.error, "FIX"))
    else:
        for slug in sorted(set(reg_by_slug) | set(breg.businesses)):
            r = reg_by_slug.get(slug)
            l = breg.businesses.get(slug)
            if r and not l:
                diffs.append(ConfigDifference("registry_only", slug, "*",
                             "in registry but not in business_registry.py", "FIX"))
                continue
            if l and not r:
                diffs.append(ConfigDifference("legacy_only", slug, "*",
                             "in business_registry.py but not in registry", "FIX"))
                continue
            diffs.extend(_compare_authoritative(slug, r, l))

    # ── registry ↔ content engine (subset / duplicate check) ──
    ce = adapter.content_engine()
    if ce.error:
        diffs.append(ConfigDifference("legacy_unreadable", "*",
                     "content_engine", ce.error, "FIX"))
    else:
        for key, l in ce.businesses.items():
            canonical = registry.resolve_slug(key)   # resolves legacy slug aliases
            if canonical is None:
                diffs.append(ConfigDifference(
                    "legacy_only", key, "content_engine_key",
                    "content engine defines a key with no registry slug/alias", "FIX"))
                continue
            r = reg_by_slug[canonical]
            legacy_env = l.get("line_token_env")
            if legacy_env and not _env_known(r, legacy_env):
                diffs.append(ConfigDifference(
                    "env_var_name_mismatch", canonical, "line_token_env",
                    f"content engine uses '{legacy_env}' not tracked as canonical/alias",
                    "FIX"))

    # ── registry ↔ executive_team targets (value mismatch) ────
    et = adapter.executive_targets()
    if not et.error:
        by_display = {b.display_name: b for b in registry.list_businesses()}
        for display, l in et.businesses.items():
            r = by_display.get(display)
            if not r:
                continue
            lt, rt = l.get("target"), r.monthly_target
            if lt is not None and rt is not None and lt != rt:
                diffs.append(ConfigDifference(
                    "value_mismatch", r.slug, "monthly_target",
                    f"executive_team target {lt} != registry {rt}", "FIX"))

    return ComparisonResult(decision=_decision(diffs), differences=diffs)


def _compare_authoritative(slug, r, l) -> List[ConfigDifference]:
    out: List[ConfigDifference] = []

    def cmp(field_name, rv, lv, severity="FIX"):
        if lv is None:
            return
        if rv is None:
            out.append(ConfigDifference("field_missing", slug, field_name,
                       f"legacy has {lv!r}, registry missing", severity))
        elif type(rv) is not type(lv) and not _num_equal(rv, lv):
            out.append(ConfigDifference("type_mismatch", slug, field_name,
                       f"registry {type(rv).__name__} vs legacy {type(lv).__name__}",
                       severity))
        elif not _values_equal(rv, lv):
            out.append(ConfigDifference("value_mismatch", slug, field_name,
                       f"registry {rv!r} vs legacy {lv!r}", severity))

    cmp("business_type", r.business_type, l.get("business_type"))
    cmp("monthly_target", r.monthly_target, l.get("monthly_target"))
    cmp("cloud_run_service", r.services.cloud_run_service, l.get("cloud_run_service"))
    cmp("timezone", r.timezone or None, l.get("timezone"))

    # active flag: legacy status "active" ⇔ registry active True / status ACTIVE
    legacy_active = (l.get("status") == "active")
    if legacy_active != r.active:
        out.append(ConfigDifference("active_mismatch", slug, "active",
                   f"registry active={r.active} vs legacy status={l.get('status')!r}", "FIX"))

    # env var names should be tracked in the registry (canonical or alias).
    for env in (l.get("spreadsheet_id_env"), l.get("line_staff_env")):
        if env and not _env_known(r, env):
            out.append(ConfigDifference("env_var_name_mismatch", slug,
                       "environment_variable_names",
                       f"legacy env name '{env}' not tracked as canonical/alias", "FIX"))
    return out


def _env_known(r, env) -> bool:
    return env in r.environment_variable_names or env in r.environment_variable_aliases


def _first_spreadsheet_env(b) -> str:
    for name in b.environment_variable_names:
        if "SPREADSHEET" in name.upper():
            return name
    return ""


def _num_equal(a, b) -> bool:
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return False


def _values_equal(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return a == b
