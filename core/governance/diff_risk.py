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
