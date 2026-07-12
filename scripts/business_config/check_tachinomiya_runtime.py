#!/usr/bin/env python3
"""TACHINOMIYA Runtime Config resolver CLI (Phase B2-2).

Resolves which config source TACHINOMIYA would use under a given runtime mode,
with SSOT-primary + legacy fallback. Secret-safe (NAMES only); no external I/O.

Usage:
    python3 scripts/business_config/check_tachinomiya_runtime.py \
        --mode SSOT_PRIMARY_WITH_LEGACY_FALLBACK --owner-approved

Exit codes:
    0  = GO
    10 = GO_WITH_FALLBACK
    20 = OWNER_APPROVAL_REQUIRED
    30 = FIX
    40 = STOP
    50 = INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {
    "GO": 0,
    "GO_WITH_FALLBACK": 10,
    "OWNER_APPROVAL_REQUIRED": 20,
    "FIX": 30,
    "STOP": 40,
    "INTERNAL_ERROR": 50,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="SHADOW_ONLY",
                        choices=["LEGACY_ONLY", "SHADOW_ONLY",
                                 "SSOT_PRIMARY_WITH_LEGACY_FALLBACK", "SSOT_ONLY"])
    parser.add_argument("--business-id", default="tachinomiya")
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    owner_approved = args.owner_approved or (
        os.getenv("YU_OWNER_APPROVED", "").strip().lower() == "true")

    try:
        from core.business_config.runtime_resolver import resolve
    except Exception as exc:
        print("【TACHINOMIYA Runtime Config Check】")
        print(f"  Decision        : INTERNAL_ERROR ({exc})")
        return EXIT["INTERNAL_ERROR"]

    r = resolve(business_id=args.business_id, mode=args.mode,
                owner_approved=owner_approved, repo_root=args.repo_root)

    print("【TACHINOMIYA Runtime Config Check】")
    print(f"  Decision        : {r['decision']}")
    print(f"  Mode            : {r['mode']}")
    print(f"  Runtime source  : {r['runtime_source']}")
    print(f"  Fallback used   : {r['fallback_used']}")
    print(f"  Fallback reason : {r['fallback_reason']}")
    print(f"  Mismatch count  : {r['mismatch_count']}")
    print(f"  Approval        : {r['approval_state']}")
    print(f"  Secret-safe     : yes (names only)")
    print(f"  External network: none")
    print(f"  Correlation id  : {r['correlation_id']}")
    nxt = {
        "GO": "SSOT を primary として使用可（mismatch 0・承認済み）",
        "GO_WITH_FALLBACK": f"SSOT 不可のため Legacy fallback（{r['fallback_reason']}）",
        "OWNER_APPROVAL_REQUIRED": "SSOT primary には owner 承認が必要",
        "FIX": "mismatch あり。fallback せず要修正",
        "STOP": "危険/禁止。切替せず停止",
        "INTERNAL_ERROR": "fail-closed（判定不能・Legacy）",
    }.get(r["decision"], "STOP扱い")
    print(f"  Next action     : {nxt}")
    return EXIT.get(r["decision"], EXIT["INTERNAL_ERROR"])


if __name__ == "__main__":
    raise SystemExit(main())
