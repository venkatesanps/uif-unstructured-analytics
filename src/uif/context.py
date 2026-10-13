"""Run context handed to every step: config, providers, registry, master data,
plus JSON helpers over the store with fixed key layout."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from uif.config import load_config
from uif.providers import Providers, build_providers
from uif.registry import Registry

M = TypeVar("M", bound=BaseModel)

# Store key layout. Only raw/ and restricted/ ever hold un-tokenized content:
# they get the tight IAM policy and KMS key in AWS (the PCI boundary).
KEYS = {
    "raw": "raw/{doc_id}/{file_name}",
    "envelope": "envelope/{doc_id}.json",
    "normalized": "restricted/normalized/{doc_id}.json",
    "guarded": "guarded/{doc_id}.json",
    "classification": "classification/{doc_id}.json",
    "extraction": "extraction/{doc_id}.json",
    "entity": "entity/{doc_id}.json",
    "validated": "validated/{doc_id}.json",
    "published": "published/{doc_id}.json",
}


@dataclass
class Context:
    cfg: dict[str, Any]
    providers: Providers
    registry: Registry
    master: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_config(cls, runtime: str | None = None, overrides: dict[str, Any] | None = None) -> "Context":
        cfg = load_config(runtime)
        for dotted, value in (overrides or {}).items():
            node = cfg
            *parents, leaf = dotted.split(".")
            for p in parents:
                node = node.setdefault(p, {})
            node[leaf] = value
        master = []
        mpath = Path(cfg["master_data"]["path"])
        if mpath.exists():
            with open(mpath, newline="") as fh:
                master = list(csv.DictReader(fh))
        return cls(cfg, build_providers(cfg), Registry(cfg["registry"]["path"]), master)

    _refs: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def reference(self, name: str) -> list[dict[str, str]]:
        """Lookup table from <reference.path>/<name>.csv (e.g. reason_codes)."""
        if name not in self._refs:
            path = Path((self.cfg.get("reference") or {}).get("path", "")) / f"{name}.csv"
            with open(path, newline="") as fh:
                self._refs[name] = list(csv.DictReader(fh))
        return self._refs[name]

    @property
    def store(self):
        return self.providers.store

    def key(self, kind: str, **kw: str) -> str:
        return KEYS[kind].format(**kw)

    def put_model(self, kind: str, model: BaseModel, **kw: str) -> str:
        k = self.key(kind, **kw)
        self.store.put_bytes(k, model.model_dump_json(indent=2).encode())
        return k

    def get_model(self, kind: str, cls: type[M], **kw: str) -> M:
        return cls.model_validate_json(self.store.get_bytes(self.key(kind, **kw)))

    def put_json(self, kind: str, data: Any, **kw: str) -> str:
        k = self.key(kind, **kw)
        self.store.put_bytes(k, json.dumps(data, indent=2, default=str).encode())
        return k

    def get_json(self, kind: str, **kw: str) -> Any:
        return json.loads(self.store.get_bytes(self.key(kind, **kw)))

    @property
    def min_classify(self) -> float:
        return float(self.cfg["thresholds"]["classify_min_confidence"])

    @property
    def default_review_below(self) -> float:
        return float(self.cfg["thresholds"]["default_review_below"])
