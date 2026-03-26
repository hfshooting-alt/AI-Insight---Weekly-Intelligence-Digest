"""Centralized configuration loader.

Reads ``scoring.yaml`` once and exposes a nested dict via ``get_config()``.
Individual modules use ``cfg("cluster.initial_threshold", 0.42)`` for
dot-path access with a fallback default.
"""

from __future__ import annotations

import os
import pathlib
from typing import Any

import yaml

_CONFIG: dict | None = None
_CONFIG_PATH = pathlib.Path(__file__).parent / "scoring.yaml"


def _load() -> dict:
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    override = os.environ.get("SCORING_YAML")
    path = pathlib.Path(override) if override else _CONFIG_PATH
    with open(path, "r", encoding="utf-8") as f:
        _CONFIG = yaml.safe_load(f) or {}
    return _CONFIG


def get_config() -> dict:
    """Return the full config dict (loaded once, cached)."""
    return _load()


def cfg(dotpath: str, default: Any = None) -> Any:
    """Dot-path lookup.  e.g. ``cfg("cluster.initial_threshold", 0.42)``."""
    d = _load()
    keys = dotpath.split(".")
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return default
        if d is None:
            return default
    return d


def reload_config() -> dict:
    """Force re-read (useful for tests)."""
    global _CONFIG
    _CONFIG = None
    return _load()
