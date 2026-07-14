"""Production Activation Preparation plan (Phase B2-7).

Produces a deploy-ready ("just before deploy") plan for the READY businesses
(catering / beauty / ryukyu_hinabe) and a TACHINOMIYA technical-readiness
summary. **No production operation**: deploy / env-update / smoke / rollback
commands are generated as candidate STRINGS only and are never executed. Secret
/ token / credential VALUES are never read or shown.

Plan decision:
    PREPARED                 readiness READY, prerequisites known, rollback ready
                             (deploy approval is the explicitly-noted next gate)
    DEPLOY_APPROVAL_REQUIRED readiness READY but a hard deploy blocker present
    MANUAL_CHECK_REQUIRED    a prerequisite (e.g. service name) is UNKNOWN
    NOT_READY                readiness not READY / out of scope
    STOP                     dangerous (secret / cross-business / etc.)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Known, non-secret production coordinates.
PROJECT_ID = "tree-beauty-ai-499303"
REGION = "asia-northeast1"
RUNTIME_MODE_ENV = "YU_CONFIG_RUNTIME_MODE"
OWNER_APPROVED_ENV = "YU_OWNER_APPROVED"
CURRENT_MODE = "LEGACY_ONLY"
PROPOSED_MODE = "OWNER_APPROVED"

READY_THREE = ("catering", "beauty", "ryukyu_hinabe")
UNKNOWN = "UNKNOWN"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _commands(service: str) -> Dict[str, str]:
    guard = "   # CANDIDATE ONLY — NOT EXECUTED"
    svc = service or UNKNOWN
    return {
        "execute": False,   # command execution flag is always false
        "deploy_command": (
            f"gcloud run services update {svc} --project {PROJECT_ID} "
            f"--region {REGION} --update-env-vars "
            f"{RUNTIME_MODE_ENV}={PROPOSED_MODE},{OWNER_APPROVED_ENV}=true" + guard),
        "env_update_command": (
            f"gcloud run services update {svc} --project {PROJECT_ID} "
            f"--region {REGION} --update-env-vars {RUNTIME_MODE_ENV}={PROPOSED_MODE}" + guard),
        "smoke_test_command": (
            f"python3 scripts/business_config/check_runtime_main_path.py "
            f"--business <business> --flag {PROPOSED_MODE} --owner-approved"),
        "rollback_command": (
            f"gcloud run services update {svc} --project {PROJECT_ID} "
            f"--region {REGION} --update-env-vars {RUNTIME_MODE_ENV}={CURRENT_MODE}" + guard),
    }


def build_production_plan(business_id: str, repo_root=None, registry=None) -> Dict[str, Any]:
    """Build the activation-preparation plan for one business (never runs anything)."""
    root = os.path.abspath(repo_root or _repo_root())
    plan: Dict[str, Any] = {
        "business_id": business_id,
        "readiness": None,
        "current_runtime_mode": CURRENT_MODE,
        "proposed_runtime_mode": PROPOSED_MODE,
        "cloud_run_service": UNKNOWN,
        "project_id": PROJECT_ID,
        "region": REGION,
        "env_var_names": [RUNTIME_MODE_ENV, OWNER_APPROVED_ENV],
        "deploy_required": True,
        "deploy_approved": False,
        "scheduler_required": False,
        "scheduler_approved": False,
        "external_send_required": False,
        "external_send_approved": False,
        "smoke_tests": [],
        "health_check": "GET /health (Cloud Run)",
        "rollback_steps": [
            f"set {RUNTIME_MODE_ENV}={CURRENT_MODE} (default)",
            "no code revert required",
            "legacy config remains authoritative",
        ],
        "command_candidates": None,
        "blockers": [],
        "warnings": [],
        "decision": "INTERNAL_ERROR",
        "next_action": None,
    }
    try:
        from .readiness import assess_business
        from .approvals import ApprovalLedger
        from .activation import verify_rollback
        from .loader import BusinessConfigRegistry

        reg = registry or BusinessConfigRegistry(repo_root=root).load()
        ledger = ApprovalLedger(repo_root=root).load()

        rd = assess_business(business_id, repo_root=root, registry=reg)
        plan["readiness"] = rd["readiness_decision"]
        plan["blockers"].extend(rd["blockers"])

        b = reg.get_business(business_id)
        service = b.services.cloud_run_service if b else None
        plan["cloud_run_service"] = service or UNKNOWN
        plan["command_candidates"] = _commands(service)
        plan["smoke_tests"] = [plan["command_candidates"]["smoke_test_command"]]

        # Approvals (all false in this phase) — recorded, not granted.
        plan["deploy_approved"] = ledger.is_deploy_approved(business_id)
        plan["scheduler_approved"] = ledger.is_scheduler_approved(business_id)
        plan["external_send_approved"] = ledger.is_external_send_approved(business_id)

        rb = verify_rollback(business_id, repo_root=root, registry=reg)
        rollback_ok = rb["rollback_ready"]

        # Decision.
        if rd["readiness_decision"] == "STOP":
            plan["decision"] = "STOP"
            plan["next_action"] = "危険を検出。停止"
        elif business_id not in READY_THREE or rd["readiness_decision"] != "READY":
            plan["decision"] = "NOT_READY"
            plan["next_action"] = f"readiness={rd['readiness_decision']}（本 phase 対象は READY 3事業）"
        elif not service or service == UNKNOWN:
            plan["decision"] = "MANUAL_CHECK_REQUIRED"
            plan["next_action"] = "cloud_run_service 名が不明。手動確認要"
        elif not rollback_ok:
            plan["decision"] = "NOT_READY"
            plan["next_action"] = "rollback 未確認"
        else:
            # Everything prepared up to the deploy gate. Deploy is the next,
            # separate owner approval (not granted here).
            plan["decision"] = "PREPARED"
            if plan["deploy_approved"]:
                plan["next_action"] = ("deploy 直前状態まで準備完了。deploy 承認済み"
                                       "（実 deploy は人間が gcloud で実行）")
                plan["warnings"].append("deploy_approved (execute via gcloud by human)")
            else:
                plan["next_action"] = ("deploy 直前状態まで準備完了。実 deploy は別途 owner 承認"
                                       "（未付与）")
                plan["warnings"].append("deploy_approval_pending (separate approval)")
        return plan
    except Exception as exc:  # fail closed
        plan["decision"] = "INTERNAL_ERROR"
        plan["blockers"].append(f"internal_error:{type(exc).__name__}")
        return plan


def build_batch(business_ids: List[str], repo_root=None, registry=None) -> Dict[str, Any]:
    results = {bid: build_production_plan(bid, repo_root=repo_root, registry=registry)
               for bid in business_ids}
    decisions = [r["decision"] for r in results.values()]
    for level in ("STOP", "INTERNAL_ERROR", "NOT_READY", "MANUAL_CHECK_REQUIRED",
                  "DEPLOY_APPROVAL_REQUIRED", "PREPARED"):
        if level in decisions:
            batch = level
            break
    else:
        batch = "PREPARED"
    from .activation import verify_batch_rollback
    return {"batch_decision": batch, "results": results,
            "rollback": verify_batch_rollback(business_ids, repo_root=repo_root,
                                               registry=registry)}


# ── TACHINOMIYA technical readiness summary ──────────────────
def tachinomiya_technical_readiness(repo_root=None) -> Dict[str, Any]:
    """Combine the read-only TACHINOMIYA audit into a technical decision."""
    root = os.path.abspath(repo_root or _repo_root())
    from .tachinomiya_audit import audit_tachinomiya
    audit = audit_tachinomiya(root)

    token = audit["threads_token"]["status"]
    gbp = audit["gbp"]["status"]
    image = audit["image"]["status"]

    manual_checks: List[str] = []
    if token != "CONFIRMED":
        manual_checks.append(f"threads_token:{token}")
    if gbp != "CONFIRMED":
        manual_checks.append(f"gbp_auth:{gbp}")

    if token == "CONFIRMED" and gbp == "CONFIRMED" and image == "PHOTO_PENDING":
        decision = "PHOTO_PENDING_READY"
        next_action = "token/GBP 確認済み。写真補充のみで READY"
    elif manual_checks:
        decision = "MANUAL_CHECK_REQUIRED"
        next_action = "token/GBP は手動確認要（値は読まない）。写真も補充要"
    elif image == "PHOTO_PENDING":
        decision = "PHOTO_PENDING_READY"
        next_action = "写真補充のみで READY"
    else:
        decision = "READY"
        next_action = "技術条件充足"

    return {
        "business_id": "tachinomiya",
        "threads_token": audit["threads_token"],
        "gbp": audit["gbp"],
        "image": audit["image"],
        "scheduler_expected": audit["scheduler_expected"],   # OFF
        "posting_executed": audit["posting_executed"],       # False
        "line_sent": False,
        "manual_checks": manual_checks,
        "decision": decision,
        "next_action": next_action,
    }
