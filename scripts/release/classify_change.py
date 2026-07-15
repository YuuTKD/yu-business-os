#!/usr/bin/env python3
"""Release OS — Change Classification CLI (Phase R2).

Thin wrapper: collects the changed paths (git or --paths) and delegates ALL
classification logic to core.governance.diff_risk.classify_change (the single
source of truth). Prints the change-report as JSON and, for CI, can emit
GitHub Actions outputs.

No production access: read-only git diff + pure classification. Never prints
secret values (diff_risk scans booleans only).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.governance import diff_risk  # noqa: E402

try:  # yaml with vendored fallback (same pattern as the rest of the repo)
    import yaml as _yaml  # type: ignore

    def _load_yaml(text):
        return _yaml.safe_load(text)
except Exception:  # pragma: no cover
    from core.registry._yaml_min import safe_load as _load_yaml


def _git_changed_paths(base: str, head: str) -> list:
    cmd = ["git", "diff", "--name-only", f"{base}...{head}"]
    out = subprocess.run(cmd, cwd=_REPO_ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        # fall back to two-dot then to committed HEAD listing; fail-closed to []
        out = subprocess.run(["git", "diff", "--name-only", base, head],
                             cwd=_REPO_ROOT, capture_output=True, text=True)
    return [p for p in out.stdout.splitlines() if p.strip()]


def _load_registry_map():
    """{business_id: {"cloud_run_service": ...}} from the registry SSOT, or None.

    Reads configs/businesses/registry.yaml directly (read-only). Fail-soft: any
    problem returns None so classification still works (businesses/services []).
    """
    path = os.path.join(_REPO_ROOT, "configs", "businesses", "registry.yaml")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = _load_yaml(fh.read())
        out = {}
        for b in (data or {}).get("businesses", []) or []:
            if not isinstance(b, dict):
                continue
            bid = b.get("id")
            svc = ((b.get("services") or {}) if isinstance(b.get("services"), dict)
                   else {}).get("cloud_run_service", "")
            if bid:
                out[bid] = {"cloud_run_service": svc}
        return out or None
    except Exception:
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Release OS change classification")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--paths", nargs="*", default=None,
                    help="explicit paths (bypass git; for testing/CI)")
    ap.add_argument("--github-output", action="store_true",
                    help="also append key=value lines to $GITHUB_OUTPUT")
    args = ap.parse_args(argv)

    paths = args.paths if args.paths is not None else _git_changed_paths(
        args.base, args.head)
    report = diff_risk.classify_change(paths, registry=_load_registry_map())
    print(json.dumps(report, ensure_ascii=False, indent=2))

    # run_scope drives CI test selection, fail-closed:
    #   FULL  = run whole suite (blocked / forced / empty-or-unknown diff)
    #   NONE  = docs-only, skip code tests (lint only)
    #   GROUPS= run only selected_test_groups
    if report["blocked"] or report["full_test_required"]:
        run_scope = "FULL"
    elif report["categories"] == ["docs_only"]:
        run_scope = "NONE"
    elif report["selected_test_groups"]:
        run_scope = "GROUPS"
    else:
        run_scope = "FULL"  # empty/ambiguous diff → fail-closed to full suite

    gh_out = os.environ.get("GITHUB_OUTPUT")
    if args.github_output and gh_out:
        with open(gh_out, "a", encoding="utf-8") as fh:
            fh.write(f"risk_level={report['risk_level']}\n")
            fh.write(f"full_test_required={str(report['full_test_required']).lower()}\n")
            fh.write(f"blocked={str(report['blocked']).lower()}\n")
            fh.write(f"run_scope={run_scope}\n")
            fh.write("selected_test_groups=" + ",".join(report["selected_test_groups"]) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
