"""Diff classification helpers for the PR governance gate (Phase D-Lite).

Pure functions only — no git, no network, no I/O. The gate collects the diff
and passes plain data in; these helpers turn changed paths + added diff text
into a risk level and a set of hard-stop signals. The final GO/FIX/STOP/
OWNER_APPROVAL decision is made by GovernanceValidator (single source of truth
for decisions); this module only gathers facts.

Secret handling: ``scan_secret_lines`` returns booleans / counts only. It NEVER
returns the matched secret value, so callers cannot accidentally print it.
"""

from __future__ import annotations

import re
from typing import Iterable, List

from .validator import BLOCKED_PATH_PREFIXES  # single source for the frozen path

# ── path buckets ──────────────────────────────────────────────
CRITICAL_PATH_PATTERNS = (
    r"(^|/)\.env(\.|$)",
    r"credentials(\.json)?$",
    r"service[_-]?account",
    r"(^|/)secrets?(\.|/|$)",
    r"private[_-]?key",
    r"client_secret",
)
HIGH_PATH_PREFIXES = (
    "core/", "scripts/", "agents/", "config/", "configs/",
    "workflows/", "apps/", ".github/workflows/",
)
HIGH_PATH_PATTERNS = (
    r"cloud[_-]?run",
    r"scheduler",
    r"gbp_api",
    r"threads_.*publish",
    r"line_notify",
    r"gmail",
)
MEDIUM_PATH_PREFIXES = ("tests/", "docs/", ".claude/", ".github/")

# ── diff-content signals (added lines only) ───────────────────
SECRET_LINE_PATTERNS = (
    r"sk-[A-Za-z0-9]{20,}",
    r"ghp_[A-Za-z0-9]{20,}",
    r"gho_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"xox[baprs]-[A-Za-z0-9-]{20,}",
    r"-----BEGIN[ A-Z0-9]*PRIVATE KEY-----",
    r"AIza[0-9A-Za-z_\-]{20,}",
    r"private_key_id\s*[:=]",
    r"client_email\s*[:=].*gserviceaccount\.com",
    r"api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{32,}",
)
# Automation-runaway signals that must hard-stop a PR.
RUNAWAY_LINE_PATTERNS = {
    "tree_beauty_activate": r"tree.?beauty.*(enable|activate|status.*active)|"
                            r"(enable|activate).*tree.?beauty",
    "daily_post_limit_change": r"daily_post_limit\s*[:=]\s*[1-9]",
    "scheduler_enable": r"scheduler.*(enable|resume|\bon\b)|--enable.*job",
}


def _norm(path: str) -> str:
    p = path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    return p


def find_blocked(paths: Iterable[str]) -> List[str]:
    """Paths under a frozen prefix (scripts/acquisition/**)."""
    out = []
    for p in paths:
        n = _norm(p)
        if any(n.startswith(pref) for pref in BLOCKED_PATH_PREFIXES):
            out.append(p)
    return out


def find_critical_paths(paths: Iterable[str]) -> List[str]:
    """Paths that are inherently CRITICAL (env / credentials / secrets)."""
    out = []
    for p in paths:
        n = _norm(p)
        if any(re.search(pat, n, re.IGNORECASE) for pat in CRITICAL_PATH_PATTERNS):
            out.append(p)
    return out


def _is_high(path: str) -> bool:
    n = _norm(path)
    if any(n.startswith(pref) for pref in HIGH_PATH_PREFIXES):
        return True
    return any(re.search(pat, n, re.IGNORECASE) for pat in HIGH_PATH_PATTERNS)


def _is_medium(path: str) -> bool:
    n = _norm(path)
    return any(n.startswith(pref) for pref in MEDIUM_PATH_PREFIXES)


def classify_paths(paths: Iterable[str]) -> str:
    """Return the highest risk level implied by the changed paths.

    CRITICAL > HIGH > MEDIUM > LOW. Note: tests/ and docs/ are MEDIUM even
    though they live outside HIGH prefixes; a lone README typo stays LOW.
    """
    paths = list(paths)
    if not paths:
        return "LOW"
    if find_critical_paths(paths):
        return "CRITICAL"
    if any(_is_high(p) for p in paths):
        return "HIGH"
    if any(_is_medium(p) for p in paths):
        return "MEDIUM"
    return "LOW"


def scan_secret_lines(added_text: str) -> bool:
    """True if any added line looks like a secret. Never returns the value."""
    if not added_text:
        return False
    for pat in SECRET_LINE_PATTERNS:
        if re.search(pat, added_text, re.IGNORECASE):
            return True
    return False


def scan_runaway(added_text: str) -> List[str]:
    """Return the names of any automation-runaway signals found in added text."""
    hits = []
    if not added_text:
        return hits
    for name, pat in RUNAWAY_LINE_PATTERNS.items():
        if re.search(pat, added_text, re.IGNORECASE):
            hits.append(name)
    return hits


# ── Phase R2: Change Classification + Test Selection ──────────────────────────
# Single source of truth for change categories and which test groups a PR needs.
# Pure and path-based (no git / no I/O). Extends — does not replace — the risk
# helpers above. GovernanceValidator remains the authority for GO/FIX/STOP; this
# only produces facts for the Release OS pipeline (test selection / staging /
# approval flags).

# Real test directories under tests/ (the only groups selection may emit besides
# the FULL sentinel). Keep in sync with the tests/ layout.
TEST_GROUPS = ("agent", "business_config", "content", "governance", "registry")
FULL = "FULL"  # sentinel meaning "run the whole suite"

# Ordered category rules. First-match wins per path is NOT used — every matching
# category is collected (a PR can be several categories). Each entry:
#   (category, path-substring/regex predicate)
# Predicates operate on the normalised path.
_CATEGORY_PATTERNS = (
    ("deployment_workflow", r"^\.github/workflows/|^deploy/|^scripts/release/|^configs/release/"),
    ("acquisition",         r"^scripts/acquisition/"),
    ("tests",               r"^tests/"),
    ("scheduler",           r"scheduler"),
    ("secret_reference",    r"(^|/)\.env(\.|$)|credentials(\.json)?$|"
                            r"service[_-]?account|(^|/)secrets?(\.|/|$)|"
                            r"private[_-]?key|client_secret"),
    ("external_send",       r"line_notify|line_distributor|daily_line|gmail|"
                            r"threads_.*publish|threads_reply|gbp_api|owner_daily"),
    ("image_policy",        r"content_policy|image_generator|image_manager|"
                            r"(^|/)[^/]*image[^/]*\.py$"),
    ("content_policy",      r"content_policy|multi_business_content_engine|"
                            r"post_theme_rules|auto_post_settings"),
    ("sns_post",            r"sns_master|threads|(^|/)post|gbp"),
    ("ssot",                r"^configs/businesses/|business_config/(config_supply|"
                            r"ssot|config_builder|readiness|activation)"),
    ("business_config",     r"^core/business_config/|^configs/business_registry|"
                            r"business_registry"),
    ("cross_business",      r"multi_business|^configs/businesses/registry\.yaml$|"
                            r"executive_team"),
    ("financial_logic",     r"cash|profit|revenue|finance|(^|/)pos_|ledger|target_manager"),
    ("cloud_run_service",   r"^Dockerfile$|entrypoint|cloud[_-]?run"),
    ("core_runtime",        r"^core/[^/]+\.py$"),
    ("docs_only",           r"^docs/|(^|/)[^/]*\.md$"),
)

# Categories that force the full suite regardless of selected groups.
FULL_TEST_CATEGORIES = frozenset({
    "core_runtime", "governance", "deployment_workflow", "secret_reference",
    "external_send", "cross_business", "ssot", "cloud_run_service", "unknown",
})

# Category → test groups it implies (real dirs only).
_CATEGORY_TEST_GROUPS = {
    "docs_only":        (),
    "tests":            (),  # specific group derived from the tests/<group>/ path
    "content_policy":   ("content", "governance"),
    "image_policy":     ("content", "governance"),
    "sns_post":         ("content",),
    "business_config":  ("business_config", "registry"),
    "ssot":             ("business_config", "registry"),
    "scheduler":        ("governance", "registry"),
    "financial_logic":  ("business_config", "governance"),
    "acquisition":      (),  # blocked anyway
    # FULL categories omitted here — they resolve to FULL below.
}

# Categories that mean a Cloud Run candidate/staging is needed downstream (R3).
_STAGING_CATEGORIES = frozenset({
    "core_runtime", "cloud_run_service", "content_policy", "image_policy",
    "sns_post", "external_send", "deployment_workflow",
})

# Governance categories (a change to the gate/validator itself).
_GOVERNANCE_PATTERN = r"^core/governance/|governance_gate|^configs/governance/"


def _detect_categories(norm_paths: List[str]) -> List[str]:
    cats: List[str] = []
    for cat, pat in _CATEGORY_PATTERNS:
        if any(re.search(pat, p, re.IGNORECASE) for p in norm_paths):
            cats.append(cat)
    if any(re.search(_GOVERNANCE_PATTERN, p, re.IGNORECASE) for p in norm_paths):
        cats.append("governance")
    return cats


def _affected_businesses(norm_paths: List[str], registry) -> List[str]:
    """Businesses named in the changed paths (best-effort, from registry ids)."""
    if not registry:
        return []
    hits = []
    for bid in registry:
        # match business id or its service token in any path
        svc = str((registry.get(bid) or {}).get("cloud_run_service", ""))
        token = bid.replace("_", "-")
        if any(bid in p or (token and token in p) or (svc and svc in p)
               for p in norm_paths):
            hits.append(bid)
    return sorted(set(hits))


def classify_change(paths, added_text: str = "", registry=None) -> dict:
    """Classify a PR's changed paths into the Release OS change-report schema.

    Pure/path-based. ``registry`` is an optional {business_id: {...}} mapping used
    only to name affected businesses/services; when absent those fields are [].
    """
    norm = [_norm(p) for p in (paths or [])]
    blocked = find_blocked(norm)
    risk = classify_paths(norm)
    categories = _detect_categories(norm)

    # Any changed path that matched no category (and is not empty) → unknown,
    # which is fail-closed (forces full test + blocks auto-progress).
    matched_any = {p: False for p in norm}
    for _cat, pat in _CATEGORY_PATTERNS:
        for p in norm:
            if re.search(pat, p, re.IGNORECASE):
                matched_any[p] = True
    if any(re.search(_GOVERNANCE_PATTERN, p, re.IGNORECASE) for p in norm):
        for p in norm:
            if re.search(_GOVERNANCE_PATTERN, p, re.IGNORECASE):
                matched_any[p] = True
    unknown_paths = [p for p, m in matched_any.items() if not m]
    if unknown_paths:
        categories.append("unknown")

    categories = sorted(set(categories))

    reasons: List[str] = [f"risk={risk}"]
    if blocked:
        reasons.append(f"blocked frozen path(s): {blocked}")
    if unknown_paths:
        reasons.append(f"unclassified path(s) → unknown: {unknown_paths}")

    full_test_required = (
        risk == "CRITICAL"
        or bool(set(categories) & FULL_TEST_CATEGORIES)
        or bool(blocked)
    )

    is_docs_only = categories == ["docs_only"]

    if full_test_required:
        selected = [FULL]
        reasons.append("full suite forced")
    elif is_docs_only:
        selected = []  # docs-only: lint only, no code tests
        reasons.append("docs-only: no test groups")
    else:
        groups: set = set()
        for c in categories:
            groups.update(_CATEGORY_TEST_GROUPS.get(c, ()))
        # a change under tests/<group>/ selects that group directly
        for p in norm:
            m = re.match(r"^tests/([^/]+)/", p)
            if m and m.group(1) in TEST_GROUPS:
                groups.add(m.group(1))
        # risk-based augmentation (LOW: target only; MEDIUM: +governance+registry;
        # HIGH: +governance). CRITICAL never reaches here (forces FULL).
        if risk == "MEDIUM":
            groups.update({"governance", "registry"})
        elif risk == "HIGH":
            groups.update({"governance"})
        # keep only real dirs
        selected = sorted(g for g in groups if g in TEST_GROUPS)

    staging_required = (not is_docs_only) and bool(
        set(categories) & _STAGING_CATEGORIES
    )
    production_approval_required = risk in ("HIGH", "CRITICAL")
    rollback_required = staging_required
    # CRITICAL / unknown / blocked must not auto-proceed.
    is_blocked = bool(blocked) or "unknown" in categories or risk == "CRITICAL"

    return {
        "risk_level": risk,
        "categories": categories,
        "affected_businesses": _affected_businesses(norm, registry),
        "affected_services": [
            str((registry or {}).get(b, {}).get("cloud_run_service", ""))
            for b in _affected_businesses(norm, registry)
            if (registry or {}).get(b, {}).get("cloud_run_service")
        ],
        "selected_test_groups": selected,
        "full_test_required": full_test_required,
        "staging_required": staging_required,
        "production_approval_required": production_approval_required,
        "rollback_required": rollback_required,
        "blocked": is_blocked,
        "reasons": reasons,
    }
