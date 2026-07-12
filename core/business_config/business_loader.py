"""Business config loader (Phase B2-3).

Thin, reusable layer that loads the legacy business config and passes it through
the feature-flagged runtime loader. In the default LEGACY_ONLY mode this is
exactly equivalent to calling ``configs.business_registry.get`` directly — the
returned object is the legacy config, unchanged.

This module does not delete or modify any existing config. It only composes the
existing legacy loader with the runtime connection hook.
"""

from __future__ import annotations

from typing import Any, Optional

from .runtime_loader import apply_runtime_config, runtime_decision


def load_business_config(business_name: str, repo_root: Optional[str] = None,
                         emit_log: bool = True) -> Any:
    """Return the config object for ``business_name`` (legacy shape preserved).

    Fails closed to legacy on any problem; never raises for a known business.
    """
    from configs.business_registry import BUSINESSES, get as get_config
    try:
        legacy = get_config(business_name)
    except ValueError:
        legacy = BUSINESSES.get(business_name)
        if legacy is None:
            raise
    return apply_runtime_config(business_name, legacy, repo_root=repo_root,
                                emit_log=emit_log)


def describe_source(business_name: str, repo_root: Optional[str] = None):
    """Return the structured runtime-source decision (no config mutation)."""
    return runtime_decision(business_name, repo_root=repo_root)
