"""Readiness Approval Ledger loader (Phase B2-6).

Reads configs/governance/readiness_approvals.yaml — the auditable record of
OWNER readiness approvals. Readiness approval is strictly separate from deploy /
Scheduler / external-send approval (all of which are false here). Read-only;
fail-closed; no secrets.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

try:
    import yaml as _yaml  # type: ignore

    def _load_yaml(text):
        return _yaml.safe_load(text)
except Exception:  # pragma: no cover
    from core.registry._yaml_min import safe_load as _load_yaml

_SECRETISH = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|-----BEGIN)")

READINESS_SCOPE = "SSOT_PRODUCTION_READINESS"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEFAULT_LEDGER_PATH = os.path.join("configs", "governance", "readiness_approvals.yaml")


class ApprovalLedger:
    def __init__(self, path: Optional[str] = None, repo_root: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root or _repo_root())
        rel = path or DEFAULT_LEDGER_PATH
        self.path = rel if os.path.isabs(rel) else os.path.join(self.repo_root, rel)
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._issues: List[str] = []
        self._load_error: Optional[str] = None
        self._loaded = False

    def load(self) -> "ApprovalLedger":
        self._by_id, self._issues, self._load_error = {}, [], None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            self._load_error = f"ledger not found: {self.path}"
            self._loaded = True
            return self
        except Exception as exc:
            self._load_error = f"failed to read ledger: {exc}"
            self._loaded = True
            return self

        if _SECRETISH.search(text):
            self._load_error = "secret-like value in approval ledger"
            self._loaded = True
            return self

        try:
            data = _load_yaml(text)
        except Exception as exc:
            self._load_error = f"failed to parse ledger: {exc}"
            self._loaded = True
            return self

        entries = (data or {}).get("approvals") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            self._load_error = "ledger has no 'approvals' list"
            self._loaded = True
            return self

        for raw in entries:
            if not isinstance(raw, dict):
                self._issues.append("approval entry is not a mapping")
                continue
            bid = str(raw.get("business_id", "")).strip()
            if not bid:
                self._issues.append("approval missing business_id")
                continue
            # scheduler / external-send approval remain forbidden in this phase.
            for forbidden in ("scheduler_approval", "external_send_approval"):
                if bool(raw.get(forbidden)):
                    self._issues.append(f"{bid}: {forbidden} must be false")
            # deploy approval is allowed but must be SCOPED (deploy_scope block),
            # never a blanket authorization.
            if bool(raw.get("deploy_approval")) and not isinstance(raw.get("deploy_scope"), dict):
                self._issues.append(f"{bid}: deploy_approval requires a deploy_scope")
            if raw.get("approved") and raw.get("approval_scope") != READINESS_SCOPE:
                self._issues.append(f"{bid}: approval_scope must be {READINESS_SCOPE}")
            self._by_id[bid] = raw
        self._loaded = True
        return self

    def _ensure(self):
        if not self._loaded:
            self.load()

    @property
    def load_error(self):
        self._ensure()
        return self._load_error

    def issues(self) -> List[str]:
        self._ensure()
        return list(self._issues)

    def get(self, business_id: str) -> Optional[Dict[str, Any]]:
        self._ensure()
        return self._by_id.get(business_id)

    def is_readiness_approved(self, business_id: str) -> bool:
        rec = self.get(business_id)
        return bool(rec and rec.get("approved")
                    and rec.get("approval_type") == "READINESS"
                    and rec.get("approval_scope") == READINESS_SCOPE)

    def is_deploy_approved(self, business_id: str) -> bool:
        rec = self.get(business_id)
        return bool(rec and rec.get("deploy_approval"))

    def is_scheduler_approved(self, business_id: str) -> bool:
        rec = self.get(business_id)
        return bool(rec and rec.get("scheduler_approval"))

    def is_external_send_approved(self, business_id: str) -> bool:
        rec = self.get(business_id)
        return bool(rec and rec.get("external_send_approval"))

    def approval_scope(self, business_id: str) -> Optional[str]:
        rec = self.get(business_id)
        return rec.get("approval_scope") if rec else None

    def deploy_scope(self, business_id: str) -> Optional[Dict[str, Any]]:
        rec = self.get(business_id)
        scope = rec.get("deploy_scope") if rec else None
        return scope if isinstance(scope, dict) else None


def load_default() -> ApprovalLedger:
    return ApprovalLedger().load()
