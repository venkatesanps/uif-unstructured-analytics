"""Doc-type registry: one folder per document type holding schema.json and prompt.md."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TAXONOMY_VERSION = "2026.10"


@dataclass(frozen=True)
class DocType:
    name: str
    version: str
    description: str
    fields: dict[str, dict[str, Any]]
    required: list[str]
    rules: list[dict[str, Any]]
    keywords: list[str]
    prompt: str
    prompt_version: str

    def field_type(self, name: str) -> str:
        return self.fields[name]["type"]

    def review_below(self, name: str, default: float) -> float:
        return float(self.fields[name].get("review_below", default))


class Registry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._types: dict[str, DocType] = {}
        for folder in sorted(p for p in (self.path / "doc_types").iterdir() if p.is_dir()):
            schema = json.loads((folder / "schema.json").read_text())
            prompt_file = folder / "prompt.md"
            prompt = prompt_file.read_text() if prompt_file.exists() else ""
            dt = DocType(
                name=schema["doc_type"],
                version=schema["version"],
                description=schema.get("description", ""),
                fields=schema["fields"],
                required=schema.get("required", []),
                rules=schema.get("rules", []),
                keywords=[k.lower() for k in schema.get("classify", {}).get("keywords", [])],
                prompt=prompt,
                prompt_version=schema.get("prompt_version", schema["version"]),
            )
            self._types[dt.name] = dt

    def get(self, name: str) -> DocType:
        return self._types[name]

    def names(self) -> list[str]:
        return list(self._types)

    def __contains__(self, name: str) -> bool:
        return name in self._types
