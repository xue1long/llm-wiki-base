# 共享 Fixture 说明(H5 加固)

## 路径

`tests/fixtures/v7_control_plane/`

## 文件

- `source_a.md` — 第一篇 source,包含 1 个明确 topic(主题一)+ 1 个 paraphrase excerpt,供跨文档 ID 唯一性测试
- `source_b.md` — 第二篇 source,与 source_a 主题名相同,但内容不同;供"同 topic slug 不同 source"测试
- `expected_ids.json` — 期望 page_id 字典,基于 `_page_id.py` 的 md5(slug)+slug(topic_title)计算

## Wave 1 lane 复用要求

- **Luna-A:** `test_v7_extract_slot_filler.py` 的 page ID 唯一性测试**必须**复用本 fixture,**禁止**新建临时 source 文件
- **Luna-B:** `test_v7_extract_failures.py` 的 enqueue_failure 幂等性测试可用本 fixture 验证 source_md5 路径
- **Luna-C:** async 迁移测试可用本 fixture 作为 source 列表

## 创建时机

Wave 0 主 agent 在本文件中记录设计后,**物理创建**目录与文件(在 Wave 0 落地阶段)。
