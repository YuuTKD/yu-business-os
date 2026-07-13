#!/usr/bin/env python3
"""TACHINOMIYA technical readiness CLI (Phase B2-7).

Read-only summary of TACHINOMIYA's Threads token / GBP auth / image / Scheduler
/ posting / LINE status. Never reads or shows token / credential VALUES, never
posts, never sends, never calls external APIs.

Usage:
    python3 scripts/business_config/check_tachinomiya_technical_readiness.py

Exit codes:
    0=PREPARED / PHOTO_PENDING_READY / 1=MANUAL_CHECK_REQUIRED / 2=NOT_READY /
    3=STOP / 4=INTERNAL_ERROR
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {"PREPARED": 0, "PHOTO_PENDING_READY": 0, "MANUAL_CHECK_REQUIRED": 1,
        "READY": 0, "ALMOST_READY": 2, "NOT_READY": 2, "STOP": 3, "INTERNAL_ERROR": 4}


def main(argv=None) -> int:
    try:
        from core.business_config.production_plan import tachinomiya_technical_readiness
    except Exception as exc:
        print("【TACHINOMIYA Technical Readiness】")
        print(f"  Decision : INTERNAL_ERROR ({exc})")
        return 4

    t = tachinomiya_technical_readiness()
    img = t["image"]
    shortage_str = ", ".join("{}+{}".format(s["theme"], s["add"]) for s in img["shortages"])
    print("【TACHINOMIYA Technical Readiness】")
    print(f"  Threads token   : {t['threads_token']['status']} "
          f"(env {t['threads_token']['env_name']} declared="
          f"{t['threads_token']['env_name_declared']})")
    print(f"  GBP auth        : {t['gbp']['status']} "
          f"(auth files present={t['gbp']['auth_files_present']})")
    print(f"  Photos          : {img['status']} "
          f"(add {img['required_additions']}: {shortage_str})")
    print(f"  Scheduler       : {t['scheduler_expected']} (unchanged)")
    print(f"  Posting         : executed={t['posting_executed']}")
    print(f"  LINE            : sent={t['line_sent']}")
    print(f"  Decision        : {t['decision']}")
    if t["manual_checks"]:
        print(f"  Manual checks   : {', '.join(t['manual_checks'])}")
    print(f"  Secret-safe     : yes (no token/credential values read)")
    print(f"  External network: none (no posting / no API call)")
    print(f"  Next action     : {t['next_action']}")
    return EXIT.get(t["decision"], 4)


if __name__ == "__main__":
    raise SystemExit(main())
