"""Business Config Registry loader (Phase B1, shadow mode).

Loads configs/businesses/registry.yaml, validates it against the schema
constants in models.py, and exposes read-only query APIs. It never reads
environment-variable VALUES, never connects to any external system, and fails
closed (INVALID_CONFIG) on any problem.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from .models import (
    ALLOWED_MIGRATION,
    ALLOWED_STATUS,
    BusinessConfig,
    ConfigDifference,
    FORBIDDEN_FIELD_NAMES,
    FORBIDDEN_MIGRATION,
    LoaderStatus,
    MigrationStatus,
    REQUIRED_FIELDS,
    Status,
    ValidationResult,
)

try:
    import yaml as _yaml  # type: ignore

    def _load_yaml(text: str):
        return _yaml.safe_load(text)
except Exception:  # pragma: no cover
    from core.registry._yaml_min import safe_load as _load_yaml

# Reuse the single-source secret scanner from the governance layer.
from core.governance.diff_risk import scan_secret_lines


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


DEFAULT_REGISTRY_PATH = os.path.join("configs", "businesses", "registry.yaml")

# Values that clearly look like secrets even if the field name is innocent.
_SECRETISH = re.compile(
    r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|-----BEGIN)"
)


class BusinessConfigRegistry:
    def __init__(self, path: Optional[str] = None, repo_root: Optional[str] = None):
        self.repo_root = os.path.abspath(repo_root or _repo_root())
        rel = path or DEFAULT_REGISTRY_PATH
        self.path = rel if os.path.isabs(rel) else os.path.join(self.repo_root, rel)
        self._by_id: Dict[str, BusinessConfig] = {}
        self._by_slug: Dict[str, BusinessConfig] = {}
        self._slug_alias: Dict[str, str] = {}
        self._issues: List[ConfigDifference] = []
        self._dupe_ids: set = set()
        self._dupe_slugs: set = set()
        self._loaded = False
        self._load_error: Optional[str] = None

    # ── loading ───────────────────────────────────────────────
    def load(self) -> "BusinessConfigRegistry":
        self._by_id, self._by_slug, self._issues = {}, {}, []
        self._slug_alias = {}
        self._dupe_ids, self._dupe_slugs = set(), set()
        self._load_error = None
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                text = fh.read()
        except FileNotFoundError:
            self._load_error = f"registry file not found: {self.path}"
            self._loaded = True
            return self
        except Exception as exc:
            self._load_error = f"failed to read registry: {exc}"
            self._loaded = True
            return self

        # Secret scan on the whole file first (fail closed on any secret value).
        if scan_secret_lines(text) or _SECRETISH.search(text):
            self._load_error = "secret-like value detected in business registry"
            self._issues.append(ConfigDifference(
                "secret_like_value", "*", "*",
                "registry contains a secret-like value (value hidden)", "STOP"))
            self._loaded = True
            return self

        try:
            data = _load_yaml(text)
        except Exception as exc:
            self._load_error = f"failed to parse registry: {exc}"
            self._loaded = True
            return self

        entries = (data or {}).get("businesses") if isinstance(data, dict) else None
        if not isinstance(entries, list):
            self._load_error = "registry has no 'businesses' list"
            self._loaded = True
            return self

        for raw in entries:
            if not isinstance(raw, dict):
                self._issues.append(ConfigDifference(
                    "invalid_entry", "*", "businesses", "entry is not a mapping", "STOP"))
                continue
            self._validate_and_add(raw)
        # Order-independent: a slug alias must not collide with any real id/slug.
        for alias, canonical_slug in self._slug_alias.items():
            if alias in self._by_id or alias in self._by_slug:
                self._issues.append(ConfigDifference(
                    "cross_business_contamination", canonical_slug, "slug_aliases",
                    f"alias '{alias}' collides with a real business id/slug", "STOP"))
        self._loaded = True
        return self

    def _validate_and_add(self, raw: dict) -> None:
        biz = BusinessConfig.from_dict(raw)
        bid = biz.id

        for req in REQUIRED_FIELDS:
            if not raw.get(req):
                self._issues.append(ConfigDifference(
                    "missing_field", bid or "?", req, "required field missing", "FIX"))
        if not bid:
            return

        # Forbidden field names anywhere in the entry → secret risk → STOP.
        for key in _walk_keys(raw):
            if key.lower() in FORBIDDEN_FIELD_NAMES:
                self._issues.append(ConfigDifference(
                    "forbidden_field", bid, key,
                    "forbidden field name (would store a secret)", "STOP"))

        if biz.status not in ALLOWED_STATUS:
            self._issues.append(ConfigDifference(
                "bad_enum", bid, "status", f"unknown status '{biz.status}'", "FIX"))
        if biz.migration_status in FORBIDDEN_MIGRATION:
            self._issues.append(ConfigDifference(
                "forbidden_migration", bid, "migration_status",
                f"'{biz.migration_status}' is not allowed in shadow mode", "STOP"))
        elif biz.migration_status not in ALLOWED_MIGRATION:
            self._issues.append(ConfigDifference(
                "bad_enum", bid, "migration_status",
                f"unknown migration_status '{biz.migration_status}'", "FIX"))

        # legacy_sources must reference paths inside the repo (no traversal).
        for ls in biz.legacy_sources:
            path_part = str(ls).split("::", 1)[0].strip()
            if path_part and self._path_escapes_repo(path_part):
                self._issues.append(ConfigDifference(
                    "legacy_source_path", bid, "legacy_sources",
                    f"path '{path_part}' escapes the repository root", "STOP"))

        # environment_variable_names must be NAMES, not values.
        for name in biz.environment_variable_names:
            if _SECRETISH.search(str(name)) or " " in str(name):
                self._issues.append(ConfigDifference(
                    "env_name_not_value", bid, "environment_variable_names",
                    "entry must be a variable NAME, not a value", "STOP"))
            elif not re.fullmatch(r"[A-Z][A-Z0-9_]*", str(name)):
                self._issues.append(ConfigDifference(
                    "env_name_format", bid, "environment_variable_names",
                    f"'{name}' is not an ENV_VAR_NAME style token", "FIX"))

        # monthly_target day/night breakdown must sum to the total.
        d, n, t = biz.monthly_target_day, biz.monthly_target_night, biz.monthly_target
        if d is not None and n is not None:
            try:
                if int(d) + int(n) != int(t):
                    self._issues.append(ConfigDifference(
                        "target_breakdown_mismatch", bid, "monthly_target",
                        f"day+night ({d}+{n}) != total ({t})", "FIX"))
            except (TypeError, ValueError):
                self._issues.append(ConfigDifference(
                    "target_breakdown_type", bid, "monthly_target",
                    "day/night/total must be integers", "FIX"))

        # environment variable aliases: legacy -> canonical (must not cycle,
        # target must be a canonical name, alias must not double as canonical).
        canon = set(biz.environment_variable_names)
        aliases = biz.environment_variable_aliases
        for legacy, canonical in aliases.items():
            if legacy in aliases.values() or canonical in aliases:
                self._issues.append(ConfigDifference(
                    "alias_cycle", bid, "environment_variable_aliases",
                    f"alias cycle involving '{legacy}'/'{canonical}'", "STOP"))
            if canonical not in canon:
                self._issues.append(ConfigDifference(
                    "unknown_alias_target", bid, "environment_variable_aliases",
                    f"alias '{legacy}' points at non-canonical '{canonical}'", "FIX"))
            if legacy in canon:
                self._issues.append(ConfigDifference(
                    "alias_is_canonical", bid, "environment_variable_aliases",
                    f"'{legacy}' is both a canonical name and an alias", "FIX"))
            if not re.fullmatch(r"[A-Z][A-Za-z0-9_]*", str(legacy)):
                self._issues.append(ConfigDifference(
                    "alias_name_format", bid, "environment_variable_aliases",
                    f"'{legacy}' is not an env-var-name style token", "FIX"))

        if bid in self._by_id:
            self._dupe_ids.add(bid)
            self._issues.append(ConfigDifference(
                "duplicate_id", bid, "id", "duplicate business id", "STOP"))
            return
        if biz.slug in self._by_slug:
            self._dupe_slugs.add(biz.slug)
            self._issues.append(ConfigDifference(
                "duplicate_slug", bid, "slug",
                f"duplicate slug '{biz.slug}'", "STOP"))
            return

        self._by_id[bid] = biz
        self._by_slug[biz.slug] = biz

        # slug aliases: legacy keys that resolve to this business. They must not
        # collide with a real business id/slug or another business's alias.
        for alias in biz.slug_aliases:
            if alias in self._by_id or alias in self._by_slug:
                self._issues.append(ConfigDifference(
                    "cross_business_contamination", bid, "slug_aliases",
                    f"alias '{alias}' collides with an existing business", "STOP"))
            elif alias in self._slug_alias and self._slug_alias[alias] != biz.slug:
                self._issues.append(ConfigDifference(
                    "cross_business_contamination", bid, "slug_aliases",
                    f"alias '{alias}' already maps to '{self._slug_alias[alias]}'", "STOP"))
            else:
                self._slug_alias[alias] = biz.slug

    # ── queries ───────────────────────────────────────────────
    def _ensure(self):
        if not self._loaded:
            self.load()

    @property
    def load_error(self) -> Optional[str]:
        self._ensure()
        return self._load_error

    def issues(self) -> List[ConfigDifference]:
        self._ensure()
        return list(self._issues)

    def list_businesses(self) -> List[BusinessConfig]:
        self._ensure()
        return list(self._by_id.values())

    def get_business(self, business_id: str) -> Optional[BusinessConfig]:
        self._ensure()
        return self._by_id.get(business_id)

    def get_business_by_slug(self, slug: str) -> Optional[BusinessConfig]:
        self._ensure()
        if slug in self._by_slug:
            return self._by_slug[slug]
        canonical = self._slug_alias.get(slug)   # resolve legacy alias key
        return self._by_slug.get(canonical) if canonical else None

    def resolve_slug(self, slug: str) -> Optional[str]:
        """Return the canonical slug for a slug or a legacy slug alias."""
        self._ensure()
        if slug in self._by_slug:
            return slug
        return self._slug_alias.get(slug)

    def resolve_env_alias(self, business_id: str, name: str) -> Optional[str]:
        """Map a (possibly legacy) env var NAME to its canonical NAME."""
        biz = self.get_business(business_id)
        if not biz:
            return None
        if name in biz.environment_variable_names:
            return name
        return biz.environment_variable_aliases.get(name)

    def is_env_known(self, business_id: str, name: str) -> bool:
        return self.resolve_env_alias(business_id, name) is not None

    def get_owner_channel_env(self, business_id: str) -> Optional[str]:
        biz = self.get_business(business_id)
        return biz.notification_policy.owner_channel_env if biz else None

    def get_staff_channel_env(self, business_id: str) -> Optional[str]:
        """Canonical staff channel env NAME (never a value)."""
        biz = self.get_business(business_id)
        return biz.notification_policy.staff_channel_env if biz else None

    def resolve_staff_env(self, business_id: str, available_names):
        """Pick the env NAME to use for staff, canonical-first, legacy fallback.

        ``available_names`` is a set of env var NAMES that exist (e.g. the keys
        of os.environ). VALUES are never read. Returns None if neither the
        canonical nor any legacy alias is available (caller must stop safely).
        """
        biz = self.get_business(business_id)
        if not biz:
            return None
        available = set(available_names or [])
        canonical = biz.notification_policy.staff_channel_env
        if canonical and canonical in available:
            return canonical
        for legacy, canon in biz.environment_variable_aliases.items():
            if canon == canonical and legacy in available:
                return legacy  # compatibility fallback
        return None

    def get_monthly_target_breakdown(self, business_id: str):
        """Return (total, day, night). total defaults to day+night if unset."""
        biz = self.get_business(business_id)
        if not biz:
            return (None, None, None)
        total, day, night = biz.monthly_target, biz.monthly_target_day, biz.monthly_target_night
        if total is None and day is not None and night is not None:
            try:
                total = int(day) + int(night)
            except (TypeError, ValueError):
                total = None
        return (total, day, night)

    def staff_send_requires_owner_approval(self, business_id: str) -> bool:
        """Staff notifications always require owner approval in Phase B1.x."""
        return True

    def get_service_config(self, business_id: str, service: str):
        biz = self.get_business(business_id)
        if not biz:
            return None
        return getattr(biz.services, service, None)

    def get_environment_variable_names(self, business_id: str) -> List[str]:
        biz = self.get_business(business_id)
        return list(biz.environment_variable_names) if biz else []

    def get_migration_status(self, business_id: str) -> Optional[str]:
        biz = self.get_business(business_id)
        return biz.migration_status if biz else None

    def resolve(self, business_id: str) -> str:
        """Return a LoaderStatus value for a business id (fails safe)."""
        self._ensure()
        if self._load_error:
            return LoaderStatus.INVALID_CONFIG.value
        if business_id in self._dupe_ids:
            return LoaderStatus.INVALID_CONFIG.value
        biz = self._by_id.get(business_id)
        if biz is None:
            return LoaderStatus.NOT_FOUND.value
        if not biz.active or biz.status != Status.ACTIVE.value:
            return LoaderStatus.INACTIVE.value
        ms = biz.migration_status
        if ms == MigrationStatus.VERIFIED.value:
            return LoaderStatus.VERIFIED.value
        if ms == MigrationStatus.LEGACY_ONLY.value:
            return LoaderStatus.LEGACY_ONLY.value
        return LoaderStatus.SHADOW_DEFINED.value

    def _path_escapes_repo(self, rel_or_abs: str) -> bool:
        if os.path.isabs(rel_or_abs):
            return True
        full = os.path.abspath(os.path.join(self.repo_root, rel_or_abs))
        root = os.path.abspath(self.repo_root)
        return not (full == root or full.startswith(root + os.sep))

    def validate(self) -> ValidationResult:
        """Aggregate registry-internal validation into a decision."""
        self._ensure()
        issues = list(self._issues)
        if self._load_error and not issues:
            issues.append(ConfigDifference("load_error", "*", "*", self._load_error, "STOP"))
        if any(i.severity == "STOP" for i in issues) or self._load_error:
            decision = "STOP"
        elif any(i.severity == "FIX" for i in issues):
            decision = "FIX"
        else:
            decision = "GO"
        return ValidationResult(decision=decision, issues=issues)


def _walk_keys(obj) -> List[str]:
    out: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_walk_keys(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_walk_keys(v))
    return out


def load_default() -> BusinessConfigRegistry:
    return BusinessConfigRegistry().load()
