#!/usr/bin/env python3
"""SSOT Production Activation Dry Run CLI (Phase B2-6).

Simulates activation for SSOT-enabled businesses. No production operation is
performed: no deploy, no Scheduler, no Cloud Run, no posting, no sends.

Usage:
    python3 scripts/business_config/dry_run_ssot_activation.py --batch ssot-enabled
    python3 scripts/business_config/dry_run_ssot_activation.py --business catering

Exit codes:
    0=DRY_RUN_GO / 1=READINESS_BLOCKED / 2=OWNER_APPROVAL_REQUIRED /
    3=DEPLOY_APPROVAL_REQUIRED / 4=STOP / 5=INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {
    "DRY_RUN_GO": 0, "READINESS_BLOCKED": 1, "OWNER_APPROVAL_REQUIRED": 2,
    "DEPLOY_APPROVAL_REQUIRED": 3, "STOP": 4, "INTERNAL_ERROR": 5,
}


def _print(res):
    print(f"  Business        : {res['business_id']}")
    print(f"  Readiness       : {res['readiness']}")
    print(f"  Owner approval  : {res['owner_approval']}")
    print(f"  Deploy approval : {res['deploy_approval']}")
    print(f"  Runtime source  : {res['runtime_source']}")
    print(f"  Config supply   : {res['config_supply']}")
    print(f"  Fallback        : {res['fallback']}")
    print(f"  Rollback        : {res['rollback']}")
    if res["blockers"]:
        print(f"  Blockers        : {', '.join(res['blockers'])}")
    print(f"  Decision        : {res['decision']}")
    print(f"  Next action     : {res['next_action']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business", default=None)
    parser.add_argument("--batch", default=None, choices=[None, "ssot-enabled"])
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    try:
        from core.business_config.activation import (
            dry_run_activation, dry_run_batch, SSOT_ENABLED)
    except Exception as exc:
        print("【SSOT Activation Dry Run】")
        print(f"  Decision : INTERNAL_ERROR ({exc})")
        return 5

    print("【SSOT Activation Dry Run】")
    if args.business:
        res = dry_run_activation(args.business, repo_root=args.repo_root)
        _print(res)
        print(f"  Secret-safe     : yes (names only)")
        print(f"  External network: none (no deploy / no posting)")
        return EXIT.get(res["decision"], 5)

    bt = dry_run_batch(list(SSOT_ENABLED), repo_root=args.repo_root)
    for bid in SSOT_ENABLED:
        _print(bt["results"][bid])
        print("  " + "-" * 40)
    print(f"  Batch decision  : {bt['batch_decision']}")
    print(f"  Batch rollback  : {bt['rollback']['all_rollback_ready']}")
    print(f"  Secret-safe     : yes (names only)")
    print(f"  External network: none (no deploy / no posting)")
    return EXIT.get(bt["batch_decision"], 5)


if __name__ == "__main__":
    raise SystemExit(main())
