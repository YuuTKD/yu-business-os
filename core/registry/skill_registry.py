"""Skill Registry loader for YU Business OS 2.0 (Phase A).

Single source of truth for which skills exist, whether they are active, where
their SKILL.md lives, and what each skill is / is not permitted to do.

Safety guarantees (enforced by tests):
    * SKILL.md files are **never read or executed** — existence is checked only.
    * No secret is ever read.
    * Paths that escape the repository root are rejected as INVALID_CONFIG
      (no path traversal, no absolute paths outside the repo).
    * Any exception during load fails **safe**: resolve() returns INVALID_CONFIG
      rather than raising.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional

from .models import (
    FallbackBehavior,
    RegistryResult,
    SkillDefinition,
    SkillStatus,
    ValidationIssue,
    Severity,
)

try:  # Prefer real PyYAML when present; fall back to the vendored subset parser.
    import yaml as _yaml  # type: ignore

    def _load_yaml(text: str):
        return _yaml.safe_load(text)
except Exception:  # pragma: no cover - exercised only when PyYAML absent
    from ._yaml_min import safe_load as _load_yaml


def _repo_root() -> str:
    # core/registry/skill_registry.py -> repo root is two levels up.
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEFAULT_REGISTRY_PATH = os.path.join("configs", "skills", "registry.yaml")


class SkillRegistry:
    def __init__(self, path: Optional[str] = None, repo_root: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root or _repo_root())
        rel = path or DEFAULT_REGISTRY_PATH
        self.path = rel if os.path.isabs(rel) else os.path.join(self.repo_root, rel)
        self._skills: Dict[str, SkillDefinition] = {}
        self._issues: List[ValidationIssue] = []
        self._duplicate_ids: set = set()
        self._loaded = False
        self._load_error: Optional[str] = None

    # ── loading ───────────────────────────────────────────────
    def load(self) -> "SkillRegistry":
        self._skills = {}
        self._issues = []
        self._duplicate_ids = set()
        self._load_error = None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = _load_yaml(fh.read())
        except FileNotFoundError:
            self._load_error = f"registry file not found: {self.path}"
            self._loaded = True
            return self
        except Exception as exc:  # malformed YAML → fail safe
            self._load_error = f"failed to parse registry: {exc}"
            self._loaded = True
            return self

        entries = (data or {}).get("skills") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            self._load_error = "registry has no 'skills' list"
            self._loaded = True
            return self

        for raw in entries:
            if not isinstance(raw, dict):
                self._issues.append(ValidationIssue(
                    Severity.FIX.value, self._relpath(), "skills", "entry is not a mapping"))
                continue
            skill = SkillDefinition.from_dict(raw)
            if not skill.id:
                self._issues.append(ValidationIssue(
                    Severity.STOP.value, self._relpath(), "id", "skill entry missing id"))
                continue
            if skill.id in self._skills:
                self._duplicate_ids.add(skill.id)
                self._issues.append(ValidationIssue(
                    Severity.FIX.value, self._relpath(), "id",
                    "duplicate skill id", entity_id=skill.id))
                continue
            self._validate_entry(skill)
            self._skills[skill.id] = skill
        self._loaded = True
        return self

    def _validate_entry(self, skill: SkillDefinition) -> None:
        # Permission sanity: skills must never claim deploy/scheduler/secret.
        p = skill.permissions
        for flag_name, flag in (("deploy", p.deploy), ("scheduler", p.scheduler),
                                ("secret_access", p.secret_access)):
            if flag:
                self._issues.append(ValidationIssue(
                    Severity.STOP.value, self._relpath(), f"permissions.{flag_name}",
                    "skill must not hold this permission (default deny)",
                    entity_id=skill.id))
        # Path safety for active skills that declare a SKILL.md.
        if skill.skill_md_path:
            if not self._path_within_repo(skill.skill_md_path):
                self._issues.append(ValidationIssue(
                    Severity.STOP.value, self._relpath(), "skill_md_path",
                    "path escapes repository root", entity_id=skill.id))
            elif skill.active and not self._md_exists(skill.skill_md_path):
                self._issues.append(ValidationIssue(
                    Severity.FIX.value, self._relpath(), "skill_md_path",
                    "active skill declares a SKILL.md that does not exist",
                    entity_id=skill.id))
        # Fallback value must be known.
        if skill.fallback_behavior not in {f.value for f in FallbackBehavior}:
            self._issues.append(ValidationIssue(
                Severity.FIX.value, self._relpath(), "fallback_behavior",
                f"unknown fallback_behavior '{skill.fallback_behavior}'",
                entity_id=skill.id))

    # ── path helpers ──────────────────────────────────────────
    def _path_within_repo(self, rel_or_abs: str) -> bool:
        candidate = rel_or_abs
        if os.path.isabs(candidate):
            full = os.path.abspath(candidate)
        else:
            full = os.path.abspath(os.path.join(self.repo_root, candidate))
        root = os.path.abspath(self.repo_root)
        return full == root or full.startswith(root + os.sep)

    def _md_exists(self, rel_or_abs: str) -> bool:
        if os.path.isabs(rel_or_abs):
            full = rel_or_abs
        else:
            full = os.path.join(self.repo_root, rel_or_abs)
        return os.path.isfile(full)

    def _relpath(self) -> str:
        try:
            return os.path.relpath(self.path, self.repo_root)
        except ValueError:
            return self.path

    # ── queries ───────────────────────────────────────────────
    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    @property
    def load_error(self) -> Optional[str]:
        self._ensure_loaded()
        return self._load_error

    def issues(self) -> List[ValidationIssue]:
        self._ensure_loaded()
        return list(self._issues)

    def all_skills(self) -> List[SkillDefinition]:
        self._ensure_loaded()
        return list(self._skills.values())

    def get_skill(self, skill_id: str) -> Optional[SkillDefinition]:
        self._ensure_loaded()
        return self._skills.get(skill_id)

    def has(self, skill_id: str) -> bool:
        self._ensure_loaded()
        return skill_id in self._skills

    def prohibited_actions(self, skill_id: str) -> List[str]:
        skill = self.get_skill(skill_id)
        return list(skill.prohibited_actions) if skill else []

    def resolve(self, skill_id: str, business: Optional[str] = None) -> RegistryResult:
        """Resolve a skill id to an actionable status (fails safe)."""
        self._ensure_loaded()

        if self._load_error:
            return RegistryResult(SkillStatus.INVALID_CONFIG.value, skill_id,
                                  reason=self._load_error)
        if skill_id in self._duplicate_ids:
            return RegistryResult(SkillStatus.INVALID_CONFIG.value, skill_id,
                                  reason="duplicate skill id")
        skill = self._skills.get(skill_id)
        if skill is None:
            # Unknown skill → do not stop everything; signal a safe logic fallback.
            return RegistryResult(SkillStatus.NOT_FOUND.value, skill_id,
                                  reason="skill not registered; apply direct logic")
        if skill.skill_md_path and not self._path_within_repo(skill.skill_md_path):
            return RegistryResult(SkillStatus.INVALID_CONFIG.value, skill_id,
                                  definition=skill, reason="skill_md_path escapes repo")
        if not skill.active:
            return self._fallback_result(skill, "skill is inactive")
        if not skill.applies_to(business):
            return RegistryResult(SkillStatus.FORBIDDEN.value, skill_id,
                                  definition=skill,
                                  reason=f"skill not applicable to business '{business}'")
        if skill.skill_md_path and self._md_exists(skill.skill_md_path):
            return RegistryResult(SkillStatus.AVAILABLE.value, skill_id,
                                  definition=skill, reason="SKILL.md present")
        # Active but SKILL.md missing/undeclared → fall back per policy.
        return self._fallback_result(skill, "SKILL.md unavailable")

    def _fallback_result(self, skill: SkillDefinition, reason: str) -> RegistryResult:
        fb = skill.fallback_behavior
        if fb == FallbackBehavior.DIRECT_SKILL_MD.value and skill.skill_md_path \
                and self._md_exists(skill.skill_md_path):
            return RegistryResult(SkillStatus.FALLBACK_DIRECT_MD.value, skill.id,
                                  definition=skill, reason=reason)
        if fb == FallbackBehavior.STOP.value:
            return RegistryResult(SkillStatus.FORBIDDEN.value, skill.id,
                                  definition=skill, reason=f"{reason}; fallback=STOP")
        if fb == FallbackBehavior.INACTIVE.value or not skill.active:
            return RegistryResult(SkillStatus.INACTIVE.value, skill.id,
                                  definition=skill, reason=reason)
        return RegistryResult(SkillStatus.FALLBACK_LOGIC.value, skill.id,
                              definition=skill, reason=f"{reason}; apply direct logic")


def load_default() -> SkillRegistry:
    return SkillRegistry().load()
