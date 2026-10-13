"""Config loading. One YAML per runtime; ${VAR} and ${VAR:-default} are expanded
from the environment so secrets and bucket names never live in the file."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def repo_root() -> Path:
    return Path(os.environ.get("UIF_HOME", Path(__file__).resolve().parents[2]))


def load_config(runtime: str | None = None, path: str | Path | None = None) -> dict[str, Any]:
    runtime = runtime or os.environ.get("RUNTIME", "local")
    path = Path(path) if path else repo_root() / "config" / f"{runtime}.yaml"
    with open(path) as fh:
        cfg = _expand(yaml.safe_load(fh))
    cfg.setdefault("runtime", runtime)
    # Resolve relative local paths against the repo root.
    root = repo_root()
    for section, key in [("store", "root"), ("warehouse", "path"), ("registry", "path"), ("master_data", "path")]:
        sec = cfg.get(section) or {}
        if sec.get(key) and not str(sec[key]).startswith(("s3://", "/")):
            sec[key] = str(root / sec[key])
    return cfg
