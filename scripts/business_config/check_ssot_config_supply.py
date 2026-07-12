#!/usr/bin/env python3
"""SSOT config supply check CLI (Phase B2-4, Batch 1).

Shows whether the runtime would receive an SSOT-derived config or fall back to
legacy for the Batch-1 businesses (tachinomiya / catering / beauty). Read-only,
secret-safe, no external I/O.

Usage:
    python3 scripts/business_config/check_ssot_config_supply.py \
        --business tachinomiya --mode LEGACY_ONLY
    python3 scripts/business_config/check_ssot_config_supply.py \
        --batch batch-1 --mode OWNER_APPROVED --owner-approved

Exit codes: 0=GO / 1=FIX / 2=STOP / 3=INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {"GO": 0, "FIX": 1, "STOP": 2, "INTERNAL_ERROR": 3,
        "OWNER_APPROVAL_REQUIRED": 1}


def _print_one(res):
    print(f"  Business        : {res['business_id']}")
    print(f"  Mode            : {res['requested_mode']}")
    print(f"  Source          : {res['runtime_source']}")
    print(f"  Shape valid     : {res['config_shape_valid']}")
    print(f"  Legacy compare  : {res['comparison_decision']}")
    print(f"  Fallback        : {res['used_fallback']} ({res['fallback_reason']})")
    for w in res["warnings"]:
        print(f"  Warning         : {w}")
    print(f"  Decision        : {res['decision']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business", default=None)
    parser.add_argument("--batch", default=None, choices=[None, "batch-1"])
    parser.add_argument("--mode", default="LEGACY_ONLY")
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    owner = args.owner_approved or (
        os.getenv("YU_OWNER_APPROVED", "").strip().lower() == "true")

    try:
        from core.business_config.config_supply import supply, supply_batch, SUPPLY_SCOPE
    except Exception as exc:
        print("【SSOT Config Supply】")
        print(f"  Decision : INTERNAL_ERROR ({exc})")
        return EXIT["INTERNAL_ERROR"]

    print("【SSOT Config Supply】")
    if args.batch == "batch-1" or (not args.business):
        bt = supply_batch(sorted(SUPPLY_SCOPE), mode=args.mode,
                          owner_approved=owner, repo_root=args.repo_root)
        for bid in sorted(bt["results"]):
            _print_one(bt["results"][bid])
            print("  " + "-" * 40)
        print(f"  Batch decision  : {bt['batch_decision']}")
        print(f"  Secret-safe     : yes (names only)")
        print(f"  External network: none")
        return EXIT.get(bt["batch_decision"], EXIT["INTERNAL_ERROR"])

    res = supply(args.business, mode=args.mode, owner_approved=owner,
                 repo_root=args.repo_root)
    _print_one(res)
    print(f"  Secret-safe     : yes (names only)")
    print(f"  External network: none")
    return EXIT.get(res["decision"], EXIT["INTERNAL_ERROR"])


if __name__ == "__main__":
    raise SystemExit(main())
