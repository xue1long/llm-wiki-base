"""Immutable, serializable contracts for one scenario-template snapshot."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..lib.write_hooks import safe_write


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def _sha256(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class TemplateSnapshot:
    template_id: str
    template_version: str
    template_hash: str
    contract_hash: str
    snapshot_path: str


@dataclass(frozen=True)
class TemplateContract:
    template_id: str
    template_version: str
    template_hash: str
    allowed_types: tuple[str, ...]
    slot_rules: dict[str, tuple[str, ...]]
    routes: dict[str, str]
    purpose: str
    analyzer_instructions: str = ""
    generator_instructions: str = ""
    semantic_rubric: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_hash": self.template_hash,
            "allowed_types": list(self.allowed_types),
            "slot_rules": {k: list(v) for k, v in sorted(self.slot_rules.items())},
            "routes": dict(sorted(self.routes.items())),
            "purpose": self.purpose,
            "analyzer_instructions": self.analyzer_instructions,
            "generator_instructions": self.generator_instructions,
            "semantic_rubric": self.semantic_rubric,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TemplateContract":
        return cls(
            template_id=str(data["template_id"]),
            template_version=str(data["template_version"]),
            template_hash=str(data["template_hash"]),
            allowed_types=tuple(str(x) for x in data["allowed_types"]),
            slot_rules={str(k): tuple(str(x) for x in v) for k, v in data["slot_rules"].items()},
            routes={str(k): str(v) for k, v in data["routes"].items()},
            purpose=str(data["purpose"]),
            analyzer_instructions=str(data.get("analyzer_instructions", "")),
            generator_instructions=str(data.get("generator_instructions", "")),
            semantic_rubric=dict(data.get("semantic_rubric", {})),
        )

    def analyzer_context(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "allowed_types": list(self.allowed_types),
            "instructions": self.analyzer_instructions,
        }

    def generator_context(self, wiki_type: str) -> dict[str, Any]:
        if wiki_type not in self.slot_rules:
            raise ValueError(f"Unknown Wiki type: {wiki_type}")
        return {
            "purpose": self.purpose,
            "wiki_type": wiki_type,
            "required_slots": list(self.slot_rules[wiki_type]),
            "route": self.routes[wiki_type],
            "instructions": self.generator_instructions,
        }


def contract_hash(contract: TemplateContract) -> str:
    return _sha256(_canonical_json(contract.to_dict()))


def snapshot_for(project_root: Path, contract: TemplateContract) -> TemplateSnapshot:
    digest = contract_hash(contract)
    path = project_root / ".llm-wiki" / "template-snapshots" / f"{digest}.json"
    return TemplateSnapshot(
        template_id=contract.template_id,
        template_version=contract.template_version,
        template_hash=contract.template_hash,
        contract_hash=digest,
        snapshot_path=str(path),
    )


def persist_template_snapshot(project_root: Path, contract: TemplateContract) -> TemplateSnapshot:
    snapshot = snapshot_for(project_root, contract)
    safe_write(snapshot.snapshot_path, _canonical_json(contract.to_dict()))
    return snapshot


def load_template_snapshot(project_root: Path, contract_hash_value: str) -> TemplateContract:
    path = project_root / ".llm-wiki" / "template-snapshots" / f"{contract_hash_value}.json"
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"template_unavailable: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"template_unavailable: {path}")
    contract = TemplateContract.from_dict(data)
    if contract_hash(contract) != contract_hash_value:
        raise ValueError(f"template hash mismatch: {contract_hash_value}")
    return contract
