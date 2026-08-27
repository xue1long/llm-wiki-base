"""Relation Registry (B-2.10 commit 2).

spec §3.6 9 类受控关系 + WikiPage 17 类 built-in 兼容历史 + x-* 自定义命名空间。

ADR: docs/adr/2026-08-26-relation-registry.md
YAML: .kc/relation_registry.yaml

API:
    RelationRegistry.load(yaml_path)  -> RelationRegistry
    RelationRegistry.save(yaml_path)  -> yaml_path (反向序列化)
    registry.is_allowed(name)         -> (allowed: bool, reason: str)
        reason ∈ {"spec", "legacy", "custom", "custom_unregistered", "unknown"}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml


# relation mode 三类 (spec / legacy / custom)
RelationMode = Literal["spec", "legacy", "custom"]


@dataclass(frozen=True)
class RelationType:
    """单条关系定义.

    Attributes:
        name: 关系名 (snake_case, 例 "is_a" / "part_of" / "x-novel-character-arc")
        mode: spec §3.6 受控 = "spec"; WikiPage 17 类 built-in = "legacy";
             x-* 命名空间 = "custom"
        spec_ref: spec 引用 (例 "§3.6" / "WikiPage built-in (legacy)")
        inverse: 逆关系名 (无则 None, 含自反与对称关系)
        description: 描述
    """

    name: str
    mode: RelationMode
    spec_ref: str | None = None
    inverse: str | None = None
    description: str = ""


@dataclass(frozen=True)
class RelationRegistry:
    """权威受控关系集合 (spec §3.6 + WikiPage 17 类 + x-* 自定义).

    Attributes:
        version: registry 版本号
        spec_version: spec 版本标识 (例 "KC v2.1 §3.6")
        spec_relations: spec §3.6 9 类受控关系 (mode: spec)
        legacy_relations: WikiPage 17 类 built-in (mode: legacy, 兼容历史)
        custom_prefix: x-* 自定义命名空间前缀
        custom_existing: 已登记的 x-* 关系名集合
    """

    version: int
    spec_version: str
    spec_relations: tuple[RelationType, ...]
    legacy_relations: tuple[RelationType, ...]
    custom_prefix: str = "x-"
    custom_existing: tuple[str, ...] = ()

    def is_allowed(self, relation_name: str) -> tuple[bool, str]:
        """校验关系是否允许使用.

        Returns:
            (allowed, reason):
            - (True, "spec")  - spec §3.6 9 类受控
            - (True, "legacy") - WikiPage 17 类 built-in (兼容历史, warn 级别)
            - (True, "custom") - x-* 命名空间已登记
            - (False, "custom_unregistered") - x-* 未登记 (需 ADR)
            - (False, "unknown") - 不在 registry 中
        """
        # 1. spec §3.6 9 类
        for rel in self.spec_relations:
            if rel.name == relation_name:
                return (True, "spec")
        # 2. WikiPage 17 类 legacy
        for rel in self.legacy_relations:
            if rel.name == relation_name:
                return (True, "legacy")
        # 3. x-* 自定义命名空间
        if relation_name.startswith(self.custom_prefix):
            if relation_name in self.custom_existing:
                return (True, "custom")
            else:
                return (False, "custom_unregistered")
        # 4. 未知
        return (False, "unknown")

    @classmethod
    def load(cls, yaml_path: Path) -> "RelationRegistry":
        """从 .kc/relation_registry.yaml 加载 registry."""
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

        def _parse_relations(items: list[dict], default_mode: RelationMode) -> tuple[RelationType, ...]:
            return tuple(
                RelationType(
                    name=item["name"],
                    mode=item.get("mode", default_mode),
                    spec_ref=item.get("spec_ref"),
                    inverse=item.get("inverse"),
                    description=item.get("description", ""),
                )
                for item in items
            )

        custom_ns = data.get("custom_namespace", {})
        return cls(
            version=data["version"],
            spec_version=data["spec_version"],
            spec_relations=_parse_relations(data.get("spec_relations", []), "spec"),
            legacy_relations=_parse_relations(data.get("legacy_relations", []), "legacy"),
            custom_prefix=custom_ns.get("prefix", "x-"),
            custom_existing=tuple(
                item["name"]
                for item in custom_ns.get("existing", [])
            ),
        )

    def save(self, yaml_path: Path) -> Path:
        """保存到 YAML (反向序列化)."""
        data = {
            "version": self.version,
            "spec_version": self.spec_version,
            "spec_relations": [
                {
                    "name": r.name,
                    "mode": r.mode,
                    "spec_ref": r.spec_ref,
                    "inverse": r.inverse,
                    "description": r.description,
                }
                for r in self.spec_relations
            ],
            "legacy_relations": [
                {
                    "name": r.name,
                    "mode": r.mode,
                    "spec_ref": r.spec_ref,
                    "inverse": r.inverse,
                    "description": r.description,
                }
                for r in self.legacy_relations
            ],
            "custom_namespace": {
                "prefix": self.custom_prefix,
                "existing": [{"name": n} for n in self.custom_existing],
            },
        }
        yaml_path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return yaml_path