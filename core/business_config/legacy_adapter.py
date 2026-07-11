"""Read-only legacy config adapter (Phase B1).

Extracts existing business config from the legacy Python modules **without
importing them** — the content engine imports openai / gspread / google-cloud
at module load, so importing would trigger heavy deps and side effects. Instead
we parse the source with ``ast`` and evaluate only pure literal dict nodes via
``ast.literal_eval`` (no exec, no eval, no code execution, no network).

The adapter never modifies any legacy file and never reads secret values (the
legacy dicts hold env-var NAMES and spreadsheet IDs; we surface names and a
boolean "has spreadsheet id" only — never token values, which are not present
in these files anyway).
"""

from __future__ import annotations

import ast
import os
from typing import Any, Dict, Optional

from .models import LegacySource


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def extract_dict_literal(file_path: str, var_name: str) -> Dict[str, Any]:
    """Return the literal dict assigned to ``var_name`` in ``file_path``.

    Raises ValueError if the file/variable is missing or the value is not a
    pure literal (fails closed — the caller marks the source as errored).
    """
    with open(file_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=file_path)
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.target is not None:
            targets = [node.target]
        else:
            continue
        for t in targets:
            if isinstance(t, ast.Name) and t.id == var_name:
                if node.value is None:
                    raise ValueError(f"{var_name} has no value")
                try:
                    value = ast.literal_eval(node.value)
                except Exception as exc:  # not a pure literal
                    raise ValueError(f"{var_name} is not a literal: {exc}")
                if not isinstance(value, dict):
                    raise ValueError(f"{var_name} is not a dict")
                return value
    raise ValueError(f"{var_name} not found in {file_path}")


class LegacyAdapter:
    def __init__(self, repo_root: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root or _repo_root())

    def _path(self, *parts) -> str:
        return os.path.join(self.repo_root, *parts)

    # ── business_registry.py :: BUSINESSES (authoritative) ─────
    def business_registry(self) -> LegacySource:
        src = LegacySource(name="configs/business_registry.py::BUSINESSES")
        try:
            raw = extract_dict_literal(
                self._path("configs", "business_registry.py"), "BUSINESSES")
        except Exception as exc:
            src.error = str(exc)
            return src
        for slug, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            line_channels = cfg.get("line_channels") or {}
            staff = (line_channels.get("staff") or {}) if isinstance(line_channels, dict) else {}
            src.businesses[slug] = {
                "slug": slug,
                "business_type": cfg.get("business_type"),
                "status": cfg.get("status"),
                "monthly_target": cfg.get("monthly_target"),
                "cloud_run_service": cfg.get("cloud_run_service"),
                "spreadsheet_id_env": cfg.get("spreadsheet_id_env"),
                "line_staff_env": staff.get("env_key") if isinstance(staff, dict) else None,
            }
        return src

    # ── multi_business_content_engine.py :: _BUSINESS_CONFIGS ──
    def content_engine(self) -> LegacySource:
        src = LegacySource(name="core/multi_business_content_engine.py::_BUSINESS_CONFIGS")
        try:
            raw = extract_dict_literal(
                self._path("core", "multi_business_content_engine.py"),
                "_BUSINESS_CONFIGS")
        except Exception as exc:
            src.error = str(exc)
            return src
        for key, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            src.businesses[key] = {
                "slug": key,
                "name": cfg.get("name"),
                "line_token_env": cfg.get("line_token_env"),
                # Never expose the spreadsheet id value; only whether one exists.
                "has_spreadsheet_id": bool(cfg.get("spreadsheet_id")),
            }
        return src

    # ── executive_team.py :: BUSINESS_TARGETS (targets) ────────
    def executive_targets(self) -> LegacySource:
        src = LegacySource(name="ceo/executive_team.py::BUSINESS_TARGETS")
        try:
            raw = extract_dict_literal(
                self._path("ceo", "executive_team.py"), "BUSINESS_TARGETS")
        except Exception as exc:
            src.error = str(exc)
            return src
        for name, cfg in raw.items():
            if not isinstance(cfg, dict):
                continue
            src.businesses[name] = {
                "display_name": name,
                "target": cfg.get("target"),
                "status": cfg.get("status"),
                "ss_env": cfg.get("ss_env"),
            }
        return src

    def all_sources(self):
        return [self.business_registry(), self.content_engine(), self.executive_targets()]
