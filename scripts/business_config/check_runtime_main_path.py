#!/usr/bin/env python3
"""Runtime main-path config decision CLI (Phase B2-3).

Shows which config source the production main path would use for a business
under the current feature flag (YU_CONFIG_RUNTIME_MODE). Read-only, secret-safe,
no external I/O. Does not change any config.

Usage:
    python3 scripts/business_config/check_runtime_main_path.py \
        [--business tachinomiya] [--flag LEGACY_ONLY|AUTO|OWNER_APPROVED] [--owner-approved]

Exit codes:
    0=GO / 10=GO_WITH_FALLBACK / 20=OWNER_APPROVAL_REQUIRED / 30=FIX /
    40=STOP / 50=INTERNAL_ERROR
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {
    "GO": 0, "GO_WITH_FALLBACK": 10, "OWNER_APPROVAL_REQUIRED": 20,
    "FIX": 30, "STOP": 40, "INTERNAL_ERROR": 50,
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--business", default="tachinomiya")
    parser.add_argument("--flag", default=None,
                        choices=[None, "LEGACY_ONLY", "AUTO", "OWNER_APPROVED"])
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    try:
        from core.business_config.runtime_loader import resolve_source
    except Exception as exc:
        print("【Runtime Main-Path Config Check】")
        print(f"  Decision : INTERNAL_ERROR ({exc})")
        return EXIT["INTERNAL_ERROR"]

    owner = args.owner_approved or (
        os.getenv("YU_OWNER_APPROVED", "").strip().lower() == "true") or None
    d = resolve_source(args.business, repo_root=args.repo_root,
                       flag=args.flag, owner_approved=owner)

    print("【Runtime Main-Path Config Check】")
    print(f"  Business        : {d['business']}")
    print(f"  Feature flag    : {d['flag']}")
    print(f"  Config source   : {d['source']}")
    print(f"  Decision        : {d['decision']}")
    print(f"  Fallback used   : {d['fallback_used']}")
    print(f"  Mismatch count  : {d['mismatch_count']}")
    print(f"  Approval        : {d['approval_state']}")
    print(f"  Reason          : {d['reason']}")
    print(f"  Secret-safe     : yes (names only)")
    print(f"  External network: none")
    return EXIT.get(d["decision"], EXIT["INTERNAL_ERROR"])


if __name__ == "__main__":
    raise SystemExit(main())
