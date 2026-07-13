#!/usr/bin/env python3
"""Production Activation Preparation plan CLI (Phase B2-7).

Shows the deploy-ready plan for the READY businesses. Read-only, secret-safe.
Generates candidate commands as strings only — nothing is executed. No deploy,
no env change, no Scheduler, no posting, no sends.

Usage:
    python3 scripts/business_config/check_activation_plan.py --batch ready-three
    python3 scripts/business_config/check_activation_plan.py --business catering

Exit codes:
    0=PREPARED / 1=MANUAL_CHECK_REQUIRED / 2=NOT_READY / 3=STOP / 4=INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {"PREPARED": 0, "PHOTO_PENDING_READY": 0, "DEPLOY_APPROVAL_REQUIRED": 1,
        "MANUAL_CHECK_REQUIRED": 1, "NOT_READY": 2, "STOP": 3, "INTERNAL_ERROR": 4}


def _print(p):
    print(f"  Business            : {p['business_id']}")
    print(f"  Readiness           : {p['readiness']}")
    print(f"  Runtime mode        : {p['current_runtime_mode']} -> {p['proposed_runtime_mode']}")
    print(f"  Cloud Run service   : {p['cloud_run_service']}")
    print(f"  Project / Region    : {p['project_id']} / {p['region']}")
    print(f"  Deploy approval     : {'APPROVED' if p['deploy_approved'] else 'NOT_APPROVED'}")
    print(f"  Scheduler approval  : {'APPROVED' if p['scheduler_approved'] else 'NOT_APPROVED'}")
    print(f"  External-send appr. : {'APPROVED' if p['external_send_approved'] else 'NOT_APPROVED'}")
    print(f"  Smoke test          : {p['smoke_tests'][0] if p['smoke_tests'] else '-'}")
    print(f"  Rollback            : {p['rollback_steps'][0]}")
    if p["blockers"]:
        print(f"  Blockers            : {', '.join(p['blockers'])}")
    if p["warnings"]:
        print(f"  Warnings            : {', '.join(p['warnings'])}")
    print(f"  Decision            : {p['decision']}")
    print(f"  Next action         : {p['next_action']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business", default=None)
    parser.add_argument("--batch", default=None, choices=[None, "ready-three"])
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    try:
        from core.business_config.production_plan import (
            build_production_plan, build_batch, READY_THREE)
    except Exception as exc:
        print("【Production Activation Preparation】")
        print(f"  Decision : INTERNAL_ERROR ({exc})")
        return 4

    print("【Production Activation Preparation】")
    if args.business:
        p = build_production_plan(args.business, repo_root=args.repo_root)
        _print(p)
        print(f"  Command execution   : DISABLED (candidates only)")
        print(f"  Secret-safe         : yes (names only)")
        print(f"  External network    : none (no deploy / no posting)")
        return EXIT.get(p["decision"], 4)

    bt = build_batch(list(READY_THREE), repo_root=args.repo_root)
    for bid in READY_THREE:
        _print(bt["results"][bid])
        print("  " + "-" * 44)
    print(f"  Batch decision      : {bt['batch_decision']}")
    print(f"  Batch rollback      : {bt['rollback']['all_rollback_ready']}")
    print(f"  Command execution   : DISABLED (candidates only)")
    print(f"  Secret-safe         : yes (names only)")
    print(f"  External network    : none")
    return EXIT.get(bt["batch_decision"], 4)


if __name__ == "__main__":
    raise SystemExit(main())
