"""SSOT Production Readiness Gate (Phase B2-5).

Audits the SSOT-enabled businesses (tachinomiya / catering / beauty /
ryukyu_hinabe) and returns a production-readiness decision **without touching
production**: no deploy, no Scheduler, no Cloud Run, no posting, no sends, no
writes. Read-only; fail-closed; secrets never read/emitted.

Decisions:
    READY                    技術条件 + owner 承認 + 運用確認が揃う（deploy は別承認）
    ALMOST_READY             非危険な運用不足（画像不足 / token 未確認 等）
    OWNER_APPROVAL_REQUIRED  技術的に準備完了・owner 承認待ち
    NOT_READY                SSOT供給不可 / 必須欠損 / 対象外
    STOP                     Secret / cross-business / 危険な有効化 / SSOT_ONLY 等
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Set

from .config_builder import SUPPLIED_BUSINESSES

# 4 businesses currently SSOT-enabled (Batch 1 + 2). pasta_pasta / z1 are out.
SSOT_ENABLED = ("tachinomiya", "catering", "beauty", "ryukyu_hinabe")

# Operational confirmations that code cannot verify. Until confirmed by the
# owner, the business is at most ALMOST_READY (never READY). This is where
# TACHINOMIYA's image shortage / token / GBP checks live.
OPERATIONAL_REQUIREMENTS: Dict[str, List[str]] = {
    "tachinomiya": ["image_stock_sufficient", "threads_token_verified",
                    "gbp_auth_verified"],
    "catering": [],
    "beauty": [],
    "ryukyu_hinabe": [],
}

_SECRETISH = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|-----BEGIN)")


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _result(business_id: str) -> Dict[str, Any]:
    return {
        "business_id": business_id,
        "ssot_status": None,
        "runtime_source": "LEGACY",
        "config_supply": None,
        "legacy_fallback": True,
        "rollback_ready": None,
        "owner_approval": "NOT_APPROVED",
        "missing_requirements": [],
        "warnings": [],
        "blockers": [],
        "readiness_decision": "NOT_READY",
        "next_action": None,
    }


def assess_business(business_id: str, owner_approved: Optional[bool] = None,
                    operational_confirmed: Optional[Set[str]] = None,
                    production_write: bool = False,
                    repo_root: Optional[str] = None, registry=None) -> Dict[str, Any]:
    """Assess one business. Never raises (INTERNAL_ERROR on failure).

    ``owner_approved`` None → read the readiness approval ledger; a bool
    overrides it (used by tests / CLI flag).
    """
    root = os.path.abspath(repo_root or _repo_root())
    confirmed = set(operational_confirmed or set())
    if owner_approved is None:
        try:
            from .approvals import ApprovalLedger
            owner_approved = ApprovalLedger(repo_root=root).load().is_readiness_approved(business_id)
        except Exception:
            owner_approved = False
    r = _result(business_id)
    r["owner_approval"] = "APPROVED" if owner_approved else "NOT_APPROVED"

    try:
        # Any explicit production-write intent is a hard stop (this gate never writes).
        if production_write:
            r["blockers"].append("production_write_requested")
            r["readiness_decision"] = "STOP"
            r["next_action"] = "本番書き込みは禁止。停止"
            return r

        if business_id not in SSOT_ENABLED:
            r["blockers"].append("out_of_ssot_scope")
            r["readiness_decision"] = "NOT_READY"
            r["next_action"] = "対象外事業（SSOT 供給スコープ外）"
            return r

        from .config_supply import supply
        from .loader import BusinessConfigRegistry

        reg = registry or BusinessConfigRegistry(repo_root=root).load()
        # A secret in the SSOT registry is a hard stop (never fall back over it).
        if reg.load_error and "secret" in reg.load_error.lower():
            r["blockers"].append("secret_like_value")
            r["readiness_decision"] = "STOP"
            r["next_action"] = "Secret 値を検出。停止"
            return r

        # Technical: does SSOT supply cleanly (assessed with approval)?
        s = supply(business_id, mode="OWNER_APPROVED", owner_approved=True,
                   repo_root=root, registry=reg)
        r["config_supply"] = s["decision"]
        r["runtime_source"] = s["runtime_source"]
        r["ssot_status"] = "SUPPLIED" if s["runtime_source"] == "SSOT" else "FALLBACK"
        r["warnings"].extend(s["warnings"])

        if s["decision"] == "STOP":
            r["blockers"].append(f"supply_stop:{s['fallback_reason']}")
            r["readiness_decision"] = "STOP"
            r["next_action"] = "危険な設定を検出。停止"
            return r

        # Secret-like scan of the supplied config (names only expected).
        if _SECRETISH.search(repr(s.get("config"))):
            r["blockers"].append("secret_like_value")
            r["readiness_decision"] = "STOP"
            r["next_action"] = "Secret 値を検出。停止"
            return r

        # Rollback: LEGACY_ONLY must restore legacy.
        rb = supply(business_id, mode="LEGACY_ONLY", repo_root=root, registry=reg)
        r["rollback_ready"] = rb["runtime_source"] == "LEGACY"
        r["legacy_fallback"] = True

        if s["runtime_source"] != "SSOT" or s["decision"] != "GO":
            r["missing_requirements"].append("ssot_supply_not_go")
            r["readiness_decision"] = "NOT_READY"
            r["next_action"] = "SSOT 供給が GO でない。legacy 側整理が必要"
            return r
        if not r["rollback_ready"]:
            r["blockers"].append("rollback_not_ready")
            r["readiness_decision"] = "NOT_READY"
            r["next_action"] = "rollback 未確認"
            return r

        # Business-specific invariants (report as warnings; violations = STOP).
        _business_invariants(business_id, root, reg, r)
        if r["readiness_decision"] == "STOP":
            return r

        # Operational confirmations the owner must make (code cannot verify).
        missing_ops = [req for req in OPERATIONAL_REQUIREMENTS.get(business_id, [])
                       if req not in confirmed]
        r["missing_requirements"].extend(missing_ops)

        # TACHINOMIYA: attach the read-only technical audit (token/GBP/image).
        if business_id == "tachinomiya":
            from .tachinomiya_audit import audit_tachinomiya
            audit = audit_tachinomiya(root)
            r["warnings"].extend(audit["blockers"])

        # Decision ladder.
        if missing_ops:
            if set(missing_ops) == {"image_stock_sufficient"}:
                # token + GBP confirmed, only photos remain.
                r["readiness_decision"] = "PHOTO_PENDING_READY"
                r["next_action"] = "写真補充のみ残り。撮影・登録後に READY"
            else:
                r["readiness_decision"] = "ALMOST_READY"
                r["next_action"] = "運用確認が未了（" + ", ".join(missing_ops) + "）→ 確認後 READY"
        elif not owner_approved:
            r["readiness_decision"] = "OWNER_APPROVAL_REQUIRED"
            r["next_action"] = "技術的に準備完了。owner 承認で次工程へ"
        else:
            r["readiness_decision"] = "READY"
            r["next_action"] = "本番接続可（deploy は別承認）"
        return r
    except Exception as exc:  # fail closed
        r["readiness_decision"] = "INTERNAL_ERROR"
        r["blockers"].append(f"internal_error:{type(exc).__name__}")
        r["next_action"] = "判定不能（fail-closed）"
        return r


def _business_invariants(business_id, root, registry, r) -> None:
    """Verify per-business safety invariants; add warnings / STOP on violation."""
    from .loader import BusinessConfigRegistry
    reg = registry or BusinessConfigRegistry(repo_root=root).load()
    ssot = reg.get_business(business_id)
    if ssot is None:
        r["blockers"].append("ssot_missing")
        r["readiness_decision"] = "STOP"
        return

    if business_id == "tachinomiya":
        total, day, night = reg.get_monthly_target_breakdown("tachinomiya")
        if (total, day, night) != (5500000, 2500000, 3000000):
            r["blockers"].append("tachinomiya_target_mismatch")
            r["readiness_decision"] = "STOP"
            return
        owner_env = ssot.notification_policy.owner_channel_env
        staff_env = ssot.notification_policy.staff_channel_env
        if not owner_env or not staff_env or owner_env == staff_env:
            r["blockers"].append("owner_staff_env_not_separated")
            r["readiness_decision"] = "STOP"
            return
        if not reg.staff_send_requires_owner_approval("tachinomiya"):
            r["blockers"].append("staff_notify_not_gated")
            r["readiness_decision"] = "STOP"
            return
        r["warnings"].append("scheduler_off_must_be_confirmed")

    if business_id == "ryukyu_hinabe":
        if reg.resolve_slug("hinabe") != "ryukyu_hinabe":
            r["blockers"].append("hinabe_alias_broken")
            r["readiness_decision"] = "STOP"
            return
        r["warnings"].append("gbp_automation_excluded")

    # catering / beauty: builder never force-activates; nothing to activate here.
    if business_id in ("catering", "beauty"):
        r["warnings"].append("no_service_activation_by_supply")


def assess_batch(business_ids: List[str], owner_approved: bool = False,
                 operational_confirmed: Optional[Dict[str, Set[str]]] = None,
                 repo_root: Optional[str] = None, registry=None) -> Dict[str, Any]:
    confirmed_map = operational_confirmed or {}
    results = {}
    for bid in business_ids:
        results[bid] = assess_business(
            bid, owner_approved=owner_approved,
            operational_confirmed=confirmed_map.get(bid), repo_root=repo_root,
            registry=registry)
    decisions = [res["readiness_decision"] for res in results.values()]
    if "STOP" in decisions:
        batch = "STOP"
    elif "INTERNAL_ERROR" in decisions:
        batch = "INTERNAL_ERROR"
    elif "NOT_READY" in decisions or "ALMOST_READY" in decisions:
        batch = "NEEDS_WORK"
    elif "OWNER_APPROVAL_REQUIRED" in decisions:
        batch = "OWNER_APPROVAL_REQUIRED"
    else:
        batch = "READY"
    return {"batch_decision": batch, "results": results}
