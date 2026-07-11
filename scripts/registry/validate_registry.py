#!/usr/bin/env python3
"""Registry & Governance integrity checker for YU Business OS 2.0 (Phase A).

Usage:
    python3 scripts/registry/validate_registry.py

Checks:
    * YAML parses (skills, agents, policies)
    * required keys present, no duplicate ids
    * skill_md_path exists for active skills / stays inside the repo
    * agent -> skill references are all defined
    * default deny: no agent holds external_send / deploy / scheduler /
      secret_access; no skill holds deploy / scheduler / secret_access
    * repository-external paths are rejected

Exit codes:
    0 = GO    (no issues)
    1 = FIX   (only FIX-severity issues)
    2 = STOP  (one or more STOP-severity issues, or config could not load)

Secrets are never read or printed by this tool.
"""

from __future__ import annotations

import os
import sys

# Make the repo root importable when run directly.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.registry.agent_registry import AgentRegistry           # noqa: E402
from core.registry.models import Severity, ValidationIssue        # noqa: E402
from core.registry.skill_registry import SkillRegistry            # noqa: E402
from core.governance.validator import GovernanceValidator         # noqa: E402


def collect_issues(repo_root=None):
    issues = []

    skills = SkillRegistry(repo_root=repo_root).load()
    agents = AgentRegistry(repo_root=repo_root).load()

    if skills.load_error:
        issues.append(ValidationIssue(Severity.STOP.value, "configs/skills/registry.yaml",
                                      "load", skills.load_error))
    if agents.load_error:
        issues.append(ValidationIssue(Severity.STOP.value, "configs/agents/registry.yaml",
                                      "load", agents.load_error))

    issues.extend(skills.issues())
    issues.extend(agents.issues())
    issues.extend(agents.validate_references(skills))

    # Governance policy must load.
    gov = GovernanceValidator(skill_registry=skills, agent_registry=agents, repo_root=repo_root)
    if gov.policy_error:
        issues.append(ValidationIssue(Severity.STOP.value, "configs/governance/policies.yaml",
                                      "load", gov.policy_error))

    counts = {
        "skills_total": len(skills.all_skills()),
        "skills_active": sum(1 for s in skills.all_skills() if s.active),
        "agents_total": len(agents.all_agents()),
        "agents_active": sum(1 for a in agents.all_agents() if a.active),
    }
    return issues, counts


def main() -> int:
    # Tests may point the checker at a fixture repo via YU_REGISTRY_ROOT.
    repo_root = os.getenv("YU_REGISTRY_ROOT") or None
    issues, counts = collect_issues(repo_root=repo_root)

    stop = [i for i in issues if i.severity == Severity.STOP.value]
    fix = [i for i in issues if i.severity == Severity.FIX.value]
    info = [i for i in issues if i.severity == Severity.INFO.value]

    print("=" * 60)
    print("YU Business OS 2.0 — Registry & Governance Validation")
    print("=" * 60)
    print(f"skills : {counts['skills_active']}/{counts['skills_total']} active")
    print(f"agents : {counts['agents_active']}/{counts['agents_total']} active")
    print(f"issues : STOP={len(stop)} FIX={len(fix)} INFO={len(info)}")
    print("-" * 60)

    for issue in stop + fix + info:
        print(issue.line())

    print("-" * 60)
    if stop:
        print("RESULT: STOP")
        return 2
    if fix:
        print("RESULT: FIX")
        return 1
    print("RESULT: GO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
