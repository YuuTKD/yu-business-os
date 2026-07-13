#!/usr/bin/env python3
"""SSOT Production Readiness CLI (Phase B2-5).

Audits SSOT-enabled businesses for production readiness. Read-only, secret-safe,
no external I/O, no deploy/Scheduler/posting/sends.

Usage:
    python3 scripts/business_config/check_ssot_readiness.py
    python3 scripts/business_config/check_ssot_readiness.py --business tachinomiya
    python3 scripts/business_config/check_ssot_readiness.py --batch ssot-enabled

Exit codes:
    0 = only READY / OWNER_APPROVAL_REQUIRED
    1 = ALMOST_READY / NOT_READY present
    2 = STOP present
    3 = INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _print(res):
    print(f"  Business        : {res['business_id']}")
    print(f"  Decision        : {res['readiness_decision']}")
    print(f"  SSOT            : {res['ssot_status']} (supply={res['config_supply']}, "
          f"source={res['runtime_source']})")
    print(f"  Legacy fallback : {res['legacy_fallback']}")
    print(f"  Rollback        : {res['rollback_ready']}")
    print(f"  Owner approval  : {res['owner_approval']}")
    if res["missing_requirements"]:
        print(f"  Missing         : {', '.join(res['missing_requirements'])}")
    if res["blockers"]:
        print(f"  Blockers        : {', '.join(res['blockers'])}")
    if res["warnings"]:
        print(f"  Warnings        : {', '.join(res['warnings'])}")
    print(f"  Next action     : {res['next_action']}")


def _exit_for(decisions) -> int:
    if any(d in ("STOP", "INTERNAL_ERROR") for d in decisions):
        return 2 if "STOP" in decisions else 3
    if any(d in ("ALMOST_READY", "NOT_READY", "PHOTO_PENDING_READY") for d in decisions):
        return 1  # not fully ready (photos / ops pending)
    return 0  # only READY / OWNER_APPROVAL_REQUIRED


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business", default=None)
    parser.add_argument("--batch", default=None, choices=[None, "ssot-enabled"])
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    # None → let the readiness approval ledger decide; True → simulate approval.
    owner = True if (args.owner_approved or
                     os.getenv("YU_OWNER_APPROVED", "").strip().lower() == "true") else None

    try:
        from core.business_config.readiness import (
            assess_business, assess_batch, SSOT_ENABLED)
    except Exception as exc:
        print("【SSOT Production Readiness】")
        print(f"  Decision : INTERNAL_ERROR ({exc})")
        return 3

    print("【SSOT Production Readiness】")
    if args.business:
        res = assess_business(args.business, owner_approved=owner,
                              repo_root=args.repo_root)
        _print(res)
        print(f"  Secret-safe     : yes (names only)")
        print(f"  External network: none")
        return _exit_for([res["readiness_decision"]])

    bt = assess_batch(list(SSOT_ENABLED), owner_approved=owner,
                      repo_root=args.repo_root)
    for bid in SSOT_ENABLED:
        _print(bt["results"][bid])
        print("  " + "-" * 40)
    print(f"  Batch decision  : {bt['batch_decision']}")
    print(f"  Secret-safe     : yes (names only)")
    print(f"  External network: none")
    return _exit_for([r["readiness_decision"] for r in bt["results"].values()])


if __name__ == "__main__":
    raise SystemExit(main())
