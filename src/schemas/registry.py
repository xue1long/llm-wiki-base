"""
Schema Registry - 知识库版本映射 + 迁移路由
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

CURRENT_VERSION = "v1.0"

MIGRATIONS: dict[tuple[str, str], "Migration"] = {}

@dataclass
class Migration:
    from_version: str
    to_version: str
    up_fn: Callable[[dict], dict] = field(repr=False)
    down_fn: Callable[[dict], dict] = field(repr=False)

    def up(self, data: dict) -> dict:
        return self.up_fn(data)

    def down(self, data: dict) -> dict:
        return self.down_fn(data)

def register_migration(
    from_ver: str,
    to_ver: str,
    up_fn: Callable[[dict], dict],
    down_fn: Callable[[dict], dict],
) -> None:
    """注册一个版本迁移路径"""
    MIGRATIONS[(from_ver, to_ver)] = Migration(from_ver, to_ver, up_fn, down_fn)

def get_migration(from_version: str, to_version: str) -> Optional[Migration]:
    """获取指定版本的迁移器"""
    return MIGRATIONS.get((from_version, to_version))

def migrate_data(data: dict, target_version: str = CURRENT_VERSION) -> dict:
    """迁移数据到目标版本"""
    current_version = data.get("schema_version", "v1.0")
    if current_version == target_version:
        return data
    migration = get_migration(current_version, target_version)
    if not migration:
        raise ValueError(f"No migration path from {current_version} to {target_version}")
    return migration.up(data)