#!/usr/bin/env python3
"""Governance Gate — local, gh-independent PR pre-flight (Phase D-Lite).

Collects the local diff (base...head), classifies risk, detects hard-stop
signals (secrets, frozen paths, automation runaway), then asks the Phase A
GovernanceValidator for the decision. The shell PR flow only reads the exit
code.

Usage:
    python3 scripts/agent/governance_gate.py [--base origin/main] [--head HEAD]
        [--branch <name>] [--agent-id <id>] [--skill-id <id>]
        [--action pr_change_review] [--owner-approved] [--json]

Exit codes (contract shared with pr_auto_flow.sh):
    0  = GO
    10 = FIX
    20 = OWNER_APPROVAL_REQUIRED
    30 = STOP
    40 = INTERNAL_ERROR   (fail-closed; shell treats as STOP)

Never prints secret / token / credential values. No network, no gh, no GitHub
API. All decisions come from GovernanceValidator (no duplicated decision rules).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

# Exit-code contract.
EXIT = {
    "GO": 0,
    "FIX": 10,
    "OWNER_APPROVAL_REQUIRED": 20,
    "STOP": 30,
    "INTERNAL_ERROR": 40,
}

_THIS = os.path.abspath(__file__)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_THIS)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _err_result(message: str) -> dict:
    return {
        "decision": "INTERNAL_ERROR",
        "risk_level": "CRITICAL",
        "owner_approval_required": False,
        "reasons": [message],
        "changed_files": [],
        "blocked_files": [],
        "warnings": ["fail-closed: treated as STOP"],
    }


# The runaway content scan skips files that legitimately contain these tokens
# (the governance engine that defines the patterns, docs that describe them, and
# tests that fixture them). Real behaviour changes live in config/business code,
# which is still scanned. The secret scan stays global.
RUNAWAY_SCAN_EXCLUDE_PREFIXES = ("docs/", "tests/", "core/governance/")
RUNAWAY_SCAN_EXCLUDE_SUFFIXES = (".md",)
RUNAWAY_SCAN_EXCLUDE_FILES = {
    "scripts/agent/governance_gate.py",
    "scripts/agent/pr_auto_flow.sh",
}


def _runaway_excluded(path: str) -> bool:
    n = path.replace("\\", "/")
    if n.startswith("./"):
        n = n[2:]
    if n in RUNAWAY_SCAN_EXCLUDE_FILES:
        return True
    if any(n.startswith(p) for p in RUNAWAY_SCAN_EXCLUDE_PREFIXES):
        return True
    return any(n.endswith(s) for s in RUNAWAY_SCAN_EXCLUDE_SUFFIXES)


def evaluate(changed_files, added_text, *, agent_id, action, skill_id,
             owner_approved, branch_name, repo_root=None, runaway_text=None):
    """Pure decision step (no git). Returns a structured result dict.

    ``added_text`` is scanned for secrets; ``runaway_text`` (defaults to
    ``added_text``) is scanned for automation-runaway signals. The git layer
    passes a runaway_text with meta files (governance engine, docs, tests)
    filtered out to avoid the detector flagging its own definitions.

    Any internal problem returns an INTERNAL_ERROR result rather than raising,
    so the caller always fails closed.
    """
    try:
        from core.governance.validator import GovernanceValidator, GovernanceRequest
        from core.governance import diff_risk
    except Exception as exc:  # import failure → fail closed
        return _err_result(f"governance import failed: {exc}")

    changed_files = [f for f in (changed_files or []) if f]
    if runaway_text is None:
        runaway_text = added_text
    warnings = []

    # Fact gathering (single-sourced in core.governance.diff_risk).
    blocked = diff_risk.find_blocked(changed_files)
    critical_paths = diff_risk.find_critical_paths(changed_files)
    risk = diff_risk.classify_paths(changed_files)

    secret_hit = diff_risk.scan_secret_lines(added_text)
    runaway = diff_risk.scan_runaway(runaway_text)

    # Elevate risk to CRITICAL on any hard signal; the validator STOPs on it.
    if secret_hit:
        risk = "CRITICAL"
        warnings.append("secret-like content detected in added lines (value hidden)")
    if runaway:
        risk = "CRITICAL"
        warnings.append("automation-runaway signal(s): " + ", ".join(runaway))
    if critical_paths:
        risk = "CRITICAL"
    if blocked:
        risk = "CRITICAL"

    try:
        validator = GovernanceValidator(repo_root=repo_root)
        if validator.policy_error:
            return _err_result(f"policy load error: {validator.policy_error}")
        req = GovernanceRequest(
            agent_id=agent_id,
            action=action,
            skill_id=skill_id,
            file_paths=changed_files,
            risk_level=risk,
            owner_approved=owner_approved,
            branch_name=branch_name,
        )
        result = validator.decide(req)
    except Exception as exc:
        return _err_result(f"validator error: {exc}")

    decision = result.decision
    if decision not in ("GO", "FIX", "STOP", "OWNER_APPROVAL_REQUIRED"):
        return _err_result(f"unknown decision from validator: {decision!r}")

    return {
        "decision": decision,
        "risk_level": result.risk_level,
        "owner_approval_required": decision == "OWNER_APPROVAL_REQUIRED",
        "reasons": list(result.reasons),
        "matched_policies": list(result.matched_policies),
        "changed_files": changed_files,
        "blocked_files": blocked,
        "critical_files": critical_paths,
        "warnings": warnings,
    }


# ── git collection (only place that shells out) ────────────────
def _git(args, repo_root):
    return subprocess.run(
        ["git", *args], cwd=repo_root,
        capture_output=True, text=True, check=True,
    ).stdout


def collect_diff(base, head, repo_root):
    """Return (changed_files, added_text, runaway_text). Raises on git failure.

    ``added_text``   = all added lines (for the global secret scan).
    ``runaway_text`` = added lines excluding meta files (docs / tests /
                       governance engine / gate scripts) for the runaway scan.
    """
    # Verify refs exist first so a bad base ref fails closed with a clear reason.
    _git(["rev-parse", "--verify", "--quiet", base], repo_root)
    name_status = _git(["diff", "--name-only", f"{base}...{head}"], repo_root)
    changed = [ln.strip() for ln in name_status.splitlines() if ln.strip()]

    diff_text = _git(["diff", f"{base}...{head}"], repo_root)
    added_all = []
    added_runaway = []
    current = None
    for ln in diff_text.splitlines():
        if ln.startswith("+++ "):
            path = ln[4:].strip()
            current = path[2:] if path.startswith("b/") else path
            continue
        if ln.startswith("+") and not ln.startswith("+++"):
            content = ln[1:]
            added_all.append(content)
            if current and current != "/dev/null" and not _runaway_excluded(current):
                added_runaway.append(content)
    return changed, "\n".join(added_all), "\n".join(added_runaway)


def _current_branch(repo_root):
    try:
        return _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_root).strip()
    except Exception:
        return None


def _print_human(result, args):
    print("【Governance Gate】")
    print(f"  Decision        : {result['decision']}")
    print(f"  Risk            : {result['risk_level']}")
    print(f"  Agent           : {args.agent_id}")
    print(f"  Action          : {args.action}")
    print(f"  Branch          : {args.branch or '(auto)'}")
    print(f"  Base            : {args.base}")
    print(f"  Changed files   : {len(result.get('changed_files', []))}")
    if result.get("blocked_files"):
        print(f"  Blocked files   : {', '.join(result['blocked_files'])}")
    if result.get("critical_files"):
        print(f"  Critical files  : {', '.join(result['critical_files'])}")
    print(f"  Owner approval  : {'required' if result['owner_approval_required'] else 'not required'}")
    for r in result.get("reasons", []):
        print(f"  Reason          : {r}")
    for w in result.get("warnings", []):
        print(f"  Warning         : {w}")
    nxt = {
        "GO": "既存フローを継続します",
        "FIX": "修正が必要です。commit/push/PRを止めます",
        "OWNER_APPROVAL_REQUIRED": "ゆうさんの承認待ち。承認なしで再開しません",
        "STOP": "即停止。危険を解消してください",
        "INTERNAL_ERROR": "fail-closed（STOP扱い）",
    }.get(result["decision"], "STOP扱い")
    print(f"  Next action     : {nxt}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Governance Gate for PR flow")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--agent-id", default="claude-code-implementation-agent")
    parser.add_argument("--skill-id", default=None)
    parser.add_argument("--action", default="pr_change_review")
    parser.add_argument("--owner-approved", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--repo-root", default=_REPO_ROOT)
    args = parser.parse_args(argv)

    # Owner approval: CLI flag OR one-shot env var. Never persisted.
    owner_approved = args.owner_approved or (
        os.getenv("YU_OWNER_APPROVED", "").strip().lower() == "true"
    )
    branch = args.branch or _current_branch(args.repo_root)

    try:
        changed, added, runaway_text = collect_diff(args.base, args.head, args.repo_root)
    except subprocess.CalledProcessError as exc:
        result = _err_result(f"git diff failed (base={args.base}): rc={exc.returncode}")
    except Exception as exc:
        result = _err_result(f"git collection error: {exc}")
    else:
        result = evaluate(
            changed, added,
            agent_id=args.agent_id, action=args.action, skill_id=args.skill_id,
            owner_approved=owner_approved, branch_name=branch,
            repo_root=args.repo_root, runaway_text=runaway_text,
        )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _print_human(result, args)

    return EXIT.get(result["decision"], EXIT["INTERNAL_ERROR"])


if __name__ == "__main__":
    raise SystemExit(main())
