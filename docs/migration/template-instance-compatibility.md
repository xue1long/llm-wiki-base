# 场景模板实例兼容迁移报告

检查时间：2026-08-21

检查器：`scripts/check_template_instances.py`

本检查只读扫描，不修改项目实例，`writes=0`。

## 总览

| 指标 | 数量 |
|---|---:|
| 实例总数 | 4 |
| 结构兼容 | 3 |
| 旧版本模板 | 0 |
| 结构不完整 | 1 |
| 写入 | 0 |

## 实例结果

| 实例 | 状态 | 发现 | 建议 |
|---|---|---|---|
| `knowledge/_batch10-20260815` | compatible | 有 `schema.md`、`purpose.md`，无页面模板 | 保持现状，继续实例级校验 |
| `knowledge/_batch50-20260815` | compatible | 有 `schema.md`、`purpose.md`，无页面模板 | 保持现状，继续实例级校验 |
| `knowledge/novel-wiki` | compatible | 页面模板为 `3.0.0`；taxonomy 和 tags 分离 | 保持现状，继续实例级校验 |
| `knowledge/demo` | incomplete | 缺少 `schema.md`、`purpose.md` | 补齐文件，或明确标记为 legacy 实例 |

## 结论

`knowledge/novel-wiki` 已符合当前小说模板版本；`knowledge/demo` 仍需补齐
`schema.md` 和 `purpose.md` 或明确标记为 legacy。不自动覆盖历史项目文件。
