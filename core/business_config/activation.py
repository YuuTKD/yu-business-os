"""SSOT Production Activation — Dry Run only (Phase B2-6).

Simulates production activation for the SSOT-enabled businesses **without doing
any production operation**: no deploy, no Scheduler, no Cloud Run env change, no
posting, no sends, no writes. It generates candidate commands as strings (never
executed) and verifies rollback readiness.

Activation status:
    DRY_RUN_GO                readiness READY + deploy approved (dry run passes)
    READINESS_BLOCKED         readiness not READY (ALMOST_READY / PHOTO_PENDING / NOT_READY)
    OWNER_APPROVAL_REQUIRED   readiness needs owner readiness approval
    DEPLOY_APPROVAL_REQUIRED  readiness READY but deploy is NOT approved (B2-6 state)
    STOP                      dangerous (secret / cross-business / etc.)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Known, non-secret production coordinates (from system_health.py).
GCP_PROJECT = "tree-beauty-ai-499303"
GCP_REGION = "asia-northeast1"
SSOT_ENABLED = ("tachinomiya", "catering", "beauty", "ryukyu_hinabe")

_ACTIVE_RUNTIME_MODE = "OWNER_APPROVED"      # candidate target mode (not applied)
_ROLLBACK_RUNTIME_MODE = "LEGACY_ONLY"       # default / rollback mode


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _cloud_run_service(business_id: str, registry, root) -> Optional[str]:
    b = registry.get_business(business_id)
    return b.services.cloud_run_service if b else None


def generate_activation_plan(business_id: str, repo_root=None, registry=None) -> Dict[str, Any]:
    """Machine-generate an activation plan (candidate commands only — never run)."""
    root = os.path.abspath(repo_root or _repo_root())
    from .loader import BusinessConfigRegistry
    reg = registry or BusinessConfigRegistry(repo_root=root).load()
    service = _cloud_run_service(business_id, reg, root) or "UNKNOWN"
    return {
        "business_id": business_id,
        "current_state": "LEGACY_ONLY (runtime default)",
        "desired_state": "SSOT primary (owner-approved) with legacy fallback",
        "environment_variable_change": {
            # NAMES only — no secret values.
            "YU_CONFIG_RUNTIME_MODE": f"{_ROLLBACK_RUNTIME_MODE} -> {_ACTIVE_RUNTIME_MODE}",
            "YU_OWNER_APPROVED": "true (one-shot, not persisted)",
        },
        "cloud_run_service": service,
        "scheduler_jobs": "UNCHANGED (no Scheduler change in this phase)",
        "runtime_mode": _ACTIVE_RUNTIME_MODE,
        "deploy_command_candidate": (
            f"gcloud run services update {service} "
            f"--project {GCP_PROJECT} --region {GCP_REGION} "
            f"--update-env-vars YU_CONFIG_RUNTIME_MODE={_ACTIVE_RUNTIME_MODE}"
            "   # CANDIDATE ONLY — NOT EXECUTED"),
        "smoke_test": (
            f"python3 scripts/business_config/check_runtime_main_path.py "
            f"--business {business_id} --flag {_ACTIVE_RUNTIME_MODE} --owner-approved"),
        "rollback_command_candidate": (
            f"gcloud run services update {service} "
            f"--project {GCP_PROJECT} --region {GCP_REGION} "
            f"--update-env-vars YU_CONFIG_RUNTIME_MODE={_ROLLBACK_RUNTIME_MODE}"
            "   # CANDIDATE ONLY — NOT EXECUTED"),
        "owner_approval_point": "deploy approval (separate from readiness approval)",
        "stop_conditions": [
            "readiness not READY", "deploy not approved", "secret detected",
            "cross-business contamination", "SSOT_ONLY requested",
        ],
        "note": "commands are candidates for documentation; execution is prohibited",
    }


def verify_rollback(business_id: str, repo_root=None, registry=None) -> Dict[str, Any]:
    """Verify (read-only) that the business can roll back to legacy."""
    root = os.path.abspath(repo_root or _repo_root())
    from .config_supply import supply
    from .loader import BusinessConfigRegistry
    reg = registry or BusinessConfigRegistry(repo_root=root).load()

    legacy = supply(business_id, mode="LEGACY_ONLY", repo_root=root, registry=reg)
    rollback_ready = legacy["runtime_source"] == "LEGACY"
    alias_ok = True
    if business_id == "ryukyu_hinabe":
        alias_ok = reg.resolve_slug("hinabe") == "ryukyu_hinabe"
    return {
        "business_id": business_id,
        "rollback_ready": rollback_ready,
        "method": f"YU_CONFIG_RUNTIME_MODE={_ROLLBACK_RUNTIME_MODE}",
        "code_revert_required": False,
        "legacy_present": legacy["config"] is not None,
        "alias_maintained": alias_ok,
        "scheduler_state": "OFF/UNCHANGED",
    }


def verify_batch_rollback(business_ids: List[str], repo_root=None, registry=None) -> Dict[str, Any]:
    results = {bid: verify_rollback(bid, repo_root=repo_root, registry=registry)
               for bid in business_ids}
    all_ready = all(r["rollback_ready"] for r in results.values())
    return {"all_rollback_ready": all_ready, "results": results,
            "method": f"YU_CONFIG_RUNTIME_MODE={_ROLLBACK_RUNTIME_MODE}"}


def dry_run_activation(business_id: str, repo_root=None, registry=None) -> Dict[str, Any]:
    """Simulate activation for one business. Never performs a production op."""
    root = os.path.abspath(repo_root or _repo_root())
    result = {
        "business_id": business_id,
        "readiness": None,
        "owner_approval": "NOT_APPROVED",
        "deploy_approval": "NOT_APPROVED",
        "runtime_source": "LEGACY",
        "config_supply": None,
        "fallback": True,
        "rollback": None,
        "blockers": [],
        "decision": "INTERNAL_ERROR",
        "next_action": None,
        "plan": None,
    }
    try:
        from .readiness import assess_business
        from .approvals import ApprovalLedger
        from .loader import BusinessConfigRegistry

        reg = registry or BusinessConfigRegistry(repo_root=root).load()
        ledger = ApprovalLedger(repo_root=root).load()

        rd = assess_business(business_id, repo_root=root, registry=reg)
        result["readiness"] = rd["readiness_decision"]
        result["owner_approval"] = rd["owner_approval"]
        result["config_supply"] = rd["config_supply"]
        result["runtime_source"] = rd["runtime_source"]
        result["blockers"].extend(rd["blockers"])

        rb = verify_rollback(business_id, repo_root=root, registry=reg)
        result["rollback"] = rb["rollback_ready"]

        deploy_approved = ledger.is_deploy_approved(business_id)
        result["deploy_approval"] = "APPROVED" if deploy_approved else "NOT_APPROVED"

        # Decision.
        if rd["readiness_decision"] == "STOP":
            result["decision"] = "STOP"
            result["next_action"] = "危険を検出。停止"
        elif rd["readiness_decision"] == "OWNER_APPROVAL_REQUIRED":
            result["decision"] = "OWNER_APPROVAL_REQUIRED"
            result["next_action"] = "readiness の owner 承認が必要"
        elif rd["readiness_decision"] != "READY":
            result["decision"] = "READINESS_BLOCKED"
            result["next_action"] = f"readiness={rd['readiness_decision']}（本番接続前に解消）"
        elif not deploy_approved:
            result["decision"] = "DEPLOY_APPROVAL_REQUIRED"
            result["next_action"] = "readiness 完了。deploy は別承認が必要（本 phase では未承認）"
        else:
            result["decision"] = "DRY_RUN_GO"
            result["next_action"] = "dry run 合格（実 deploy は別途）"

        result["plan"] = generate_activation_plan(business_id, repo_root=root, registry=reg)
        return result
    except Exception as exc:  # fail closed
        result["decision"] = "INTERNAL_ERROR"
        result["blockers"].append(f"internal_error:{type(exc).__name__}")
        return result


def dry_run_batch(business_ids: List[str], repo_root=None, registry=None) -> Dict[str, Any]:
    results = {bid: dry_run_activation(bid, repo_root=repo_root, registry=registry)
               for bid in business_ids}
    decisions = [r["decision"] for r in results.values()]
    # Worst-case aggregation.
    for level in ("STOP", "INTERNAL_ERROR", "READINESS_BLOCKED",
                  "OWNER_APPROVAL_REQUIRED", "DEPLOY_APPROVAL_REQUIRED", "DRY_RUN_GO"):
        if level in decisions:
            batch = level
            break
    else:
        batch = "DRY_RUN_GO"
    return {"batch_decision": batch, "results": results,
            "rollback": verify_batch_rollback(business_ids, repo_root=repo_root,
                                               registry=registry)}
