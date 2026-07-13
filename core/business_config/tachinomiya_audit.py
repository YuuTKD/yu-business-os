"""TACHINOMIYA technical readiness audit (Phase B2-6).

Read-only, secret-safe audit of the three known TACHINOMIYA blockers:
Threads token, GBP auth, and image stock. It inspects only env-var NAMES,
file EXISTENCE and known inventory snapshots — never token / credential VALUES,
never `.env` / Secret Manager, never external APIs, never posting.

Where validity/expiry cannot be verified from the repo alone, the status is
MANUAL_CHECK_REQUIRED (the owner must confirm), which keeps TACHINOMIYA at
ALMOST_READY. If only images remain, the readiness gate reports
PHOTO_PENDING_READY.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

# Env var NAMES only (never values).
THREADS_TOKEN_ENV = "THREADS_ACCESS_TOKEN"
GBP_ACCOUNT_ENV = "GOOGLE_BUSINESS_ACCOUNT_ID"
GBP_LOCATION_ENV = "GOOGLE_BUSINESS_LOCATION_ID"

# Known image inventory snapshot (from prior audits). Re-confirm on upload; this
# module never reads GCS / IMAGE_LIBRARY and never writes anything.
IMAGE_INVENTORY = {
    "interior": 1, "drink": 3, "exterior": 4, "BAR": 6, "sata_andagi": 9,
    "food": 51, "product": 19, "event": 3,
}
IMAGE_TARGETS = {
    "interior": 5, "drink": 8, "exterior": 10, "BAR": 10, "sata_andagi": 12,
}
CRITICAL_THEMES = ("interior", "drink", "exterior")


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _name_referenced(rel_path: str, name: str, root: str) -> bool:
    """True if an env-var NAME appears in a repo source file (names, not values)."""
    p = os.path.join(root, rel_path)
    if not os.path.isfile(p):
        return False
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as fh:
            return name in fh.read()
    except Exception:
        return False


def audit_threads_token(repo_root=None) -> Dict[str, Any]:
    root = os.path.abspath(repo_root or _repo_root())
    declared = _name_referenced("core/threads_reply_publisher.py", THREADS_TOKEN_ENV, root)
    return {
        "env_name": THREADS_TOKEN_ENV,          # NAME only
        "env_name_declared": declared,
        # Expiry/validity live in Cloud Run env / Meta and cannot be verified
        # from the repo without reading a secret → manual confirmation required.
        "status": "MANUAL_CHECK_REQUIRED" if declared else "MISSING",
        "detail": ("token env name is declared in code; 期限/有効性はリポジトリからは"
                   "検証不可（Meta Developers で要確認）" if declared
                   else "token env name not referenced"),
    }


def audit_gbp(repo_root=None) -> Dict[str, Any]:
    root = os.path.abspath(repo_root or _repo_root())
    # File EXISTENCE only — contents are never opened.
    client_secrets = os.path.isfile(os.path.join(root, "backups", "gbp_client_secrets.json"))
    oauth_tokens = os.path.isfile(os.path.join(root, "backups", "gbp_oauth_tokens.json"))
    account_env = _name_referenced("core/entrypoint.py", GBP_ACCOUNT_ENV, root)
    location_env = _name_referenced("core/entrypoint.py", GBP_LOCATION_ENV, root)
    artifacts_present = client_secrets and oauth_tokens
    return {
        "auth_files_present": artifacts_present,
        "account_env_name": GBP_ACCOUNT_ENV,
        "location_env_name": GBP_LOCATION_ENV,
        "env_names_declared": account_env and location_env,
        "status": "MANUAL_CHECK_REQUIRED" if artifacts_present else "MISSING",
        "detail": ("GBP 認証アーティファクトは存在。有効性/期限はリポジトリからは検証不可"
                   "（GCP コンソールで要確認）" if artifacts_present
                   else "GBP auth artifacts not found"),
    }


def audit_image_inventory() -> Dict[str, Any]:
    shortages: List[Dict[str, Any]] = []
    for theme in CRITICAL_THEMES:
        have = IMAGE_INVENTORY.get(theme, 0)
        need = IMAGE_TARGETS.get(theme, 0)
        if have < need:
            shortages.append({"theme": theme, "have": have, "target": need,
                              "add": need - have})
    status = "PHOTO_PENDING" if shortages else "OK"
    return {
        "status": status,
        "shortages": shortages,
        "priority_themes": [s["theme"] for s in shortages],
        "required_additions": sum(s["add"] for s in shortages),
        "note": "inventory snapshot from prior audit; re-confirm on upload",
    }


def audit_tachinomiya(repo_root=None) -> Dict[str, Any]:
    """Combined audit. Returns statuses + which operational requirements are
    auto-confirmed (none can be, safely) and remaining blockers."""
    token = audit_threads_token(repo_root)
    gbp = audit_gbp(repo_root)
    image = audit_image_inventory()

    auto_confirmed: List[str] = []          # nothing is safely auto-confirmable
    blockers: List[str] = []
    if token["status"] != "CONFIRMED":
        blockers.append(f"threads_token:{token['status']}")
    if gbp["status"] != "CONFIRMED":
        blockers.append(f"gbp_auth:{gbp['status']}")
    if image["status"] == "PHOTO_PENDING":
        blockers.append("image_stock:PHOTO_PENDING")

    return {
        "threads_token": token,
        "gbp": gbp,
        "image": image,
        "auto_confirmed_requirements": auto_confirmed,
        "blockers": blockers,
        "scheduler_expected": "OFF",         # must remain OFF (no change here)
        "posting_executed": False,
    }
