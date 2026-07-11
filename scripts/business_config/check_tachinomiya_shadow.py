#!/usr/bin/env python3
"""TACHINOMIYA SSOT Shadow check CLI (Phase B2-1).

Compares the shadow SSOT against the Legacy config for TACHINOMIYA and prints a
structured, secret-safe result. The runtime source is always LEGACY.

Usage:
    python3 scripts/business_config/check_tachinomiya_shadow.py [--mode SHADOW_ONLY|ENFORCE_COMPARE|OFF]

Exit codes:
    0 = GO / 1 = FIX / 2 = STOP / 3 = INTERNAL_ERROR (fail-closed)

Never prints token / secret / env VALUES — only NAMES and non-secret scalars.
"""

from __future__ import annotations

import argparse
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {"GO": 0, "FIX": 1, "STOP": 2, "INTERNAL_ERROR": 3}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="SHADOW_ONLY",
                        choices=["OFF", "SHADOW_ONLY", "ENFORCE_COMPARE"])
    parser.add_argument("--repo-root", default=None)
    args = parser.parse_args(argv)

    try:
        from core.business_config.shadow_adapter import compare_tachinomiya
    except Exception as exc:
        print("【TACHINOMIYA SSOT Shadow Check】")
        print(f"  Decision        : INTERNAL_ERROR ({exc})")
        return EXIT["INTERNAL_ERROR"]

    r = compare_tachinomiya(mode=args.mode, repo_root=args.repo_root)

    print("【TACHINOMIYA SSOT Shadow Check】")
    print(f"  Decision        : {r['decision']}")
    print(f"  Mode            : {r['mode']}")
    print(f"  Runtime source  : {r['runtime_source']}")
    print(f"  Mismatch count  : {r['mismatch_count']}")
    if r["mismatches"]:
        for m in r["mismatches"]:
            note = f" ({m['note']})" if m.get("note") else ""
            print(f"  Field           : [{m['severity']}] {m['field']}"
                  f" ssot={m['ssot']!r} legacy={m['legacy']!r}{note}")
    print(f"  Secret-safe     : yes (names only)")
    print(f"  External network: none")
    print(f"  Correlation id  : {r['correlation_id']}")
    nxt = {
        "GO": "Legacy と SSOT が一致。runtime は LEGACY のまま継続",
        "FIX": "非危険な差分あり。legacy 側の整理を検討（本番切替はしない）",
        "STOP": "危険な差分。切替せず停止",
        "INTERNAL_ERROR": "fail-closed（判定不能）",
    }.get(r["decision"], "STOP扱い")
    print(f"  Next action     : {nxt}")
    return EXIT.get(r["decision"], EXIT["INTERNAL_ERROR"])


if __name__ == "__main__":
    raise SystemExit(main())
