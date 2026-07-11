#!/usr/bin/env python3
"""Business Config validation CLI (Phase B1, shadow mode).

Loads the shadow registry, validates it, statically reads legacy config (no
import/exec), compares them, and prints a human-readable report.

Usage:
    python3 scripts/business_config/validate_business_configs.py

Exit codes:
    0 = GO             registry valid and matches authoritative legacy
    1 = FIX            non-dangerous divergence(s) reported (do not auto-fix)
    2 = STOP           secret / contamination / duplicate / production claim
    3 = INTERNAL_ERROR fail-closed

Secret values are never read or printed.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

EXIT = {"GO": 0, "FIX": 1, "STOP": 2, "INTERNAL_ERROR": 3}


def run(repo_root=None) -> int:
    try:
        from core.business_config.loader import BusinessConfigRegistry
        from core.business_config.legacy_adapter import LegacyAdapter
        from core.business_config.comparator import compare
    except Exception as exc:  # fail closed
        print("【Business Config Validation】")
        print(f"  Decision : INTERNAL_ERROR")
        print(f"  Reason   : import failed: {exc}")
        return EXIT["INTERNAL_ERROR"]

    try:
        registry = BusinessConfigRegistry(repo_root=repo_root).load()
        adapter = LegacyAdapter(repo_root=repo_root)
        result = compare(registry, adapter)
    except Exception as exc:
        print("【Business Config Validation】")
        print(f"  Decision : INTERNAL_ERROR")
        print(f"  Reason   : {exc}")
        return EXIT["INTERNAL_ERROR"]

    businesses = registry.list_businesses()
    stop = result.by_severity("STOP")
    fix = result.by_severity("FIX")
    info = result.by_severity("INFO")
    protected_violations = [d for d in result.differences
                            if d.kind in ("forbidden_field", "forbidden_migration")]
    secretish = [d for d in result.differences
                 if d.kind in ("secret_like_value", "env_name_not_value")]

    print("【Business Config Validation】")
    print(f"  Decision            : {result.decision}")
    print(f"  Businesses          : {len(businesses)} "
          f"(active {sum(1 for b in businesses if b.active)})")
    print(f"  Registry status     : {'INVALID' if registry.load_error else 'loaded'}")
    print(f"  Legacy sources      : business_registry.py, _BUSINESS_CONFIGS, "
          f"executive_team.py (static read)")
    print(f"  Mismatches          : STOP={len(stop)} FIX={len(fix)} INFO={len(info)}")
    print(f"  Protected violations: {len(protected_violations)}")
    print(f"  Secret-like values  : {len(secretish)}")
    ms = sorted({b.migration_status for b in businesses})
    print(f"  Migration status    : {', '.join(ms) if ms else '(none)'}")
    print("  " + "-" * 56)
    for d in stop + fix + info:
        print("  " + d.line())
    print("  " + "-" * 56)

    nxt = {
        "GO": "整合。Shadow のまま Phase B2 の接続設計へ",
        "FIX": "差分あり。自動上書きせず legacy 側の整理を検討（Phase B2）",
        "STOP": "危険設定を検出。解消するまで進めない",
        "INTERNAL_ERROR": "fail-closed。判定不能",
    }.get(result.decision, "STOP扱い")
    print(f"  Next action         : {nxt}")
    return EXIT.get(result.decision, EXIT["INTERNAL_ERROR"])


def main() -> int:
    repo_root = os.getenv("YU_BIZCONFIG_ROOT") or None
    return run(repo_root=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
