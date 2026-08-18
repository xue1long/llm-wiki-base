# 标签规范化与批量摄入 Gate 整改方案

> 关联计划：`docs/superpowers/plans/2026-08-18-architecture-remediation.md`
>
> 目标项目：`knowledge/novel-wiki`
>
> 当前状态：batch 1–7 已完成；batch 8 已生成 20 个源文件，但 gate re-check 因标签失败。

## 1. 结论

采用“提示词 + LLM 输出后处理 + 统一写盘兜底 + Gate 共用规则”的混合方案。

不能只修提示词，也不能只在落盘后静默删除：

- 只修提示词：LLM 仍可能偶发输出非法标签，`extra_pages`、旧页面和其他入口也会绕过提示词。
- 只修落盘：容易静默丢失有价值标签，也无法保证 Gate、CLI 和迁移工具使用同一语义。
- 混合方案：提示词降低错误率，代码流程保证确定性，Gate 复用同一规范化规则。

## 2. 已确认的根因

### 2.1 生产代码已有部分规范化，但边界不完整

`src/pipeline/generator.py` 已有 `_normalize_tags()`，并在新生成页面路径中调用。但 `commit_ingest()` 对 `extra_pages` 的写盘没有统一调用规范化器。

因此以下页面可能绕过 Generator 的规范化：

- 反向关系产生的 `extra_pages`
- 旧页面重新写盘
- batch/重试/迁移等非标准 Generator 入口

### 2.2 Gate 使用严格规则

`src/wiki/features/batch_gate.py` 调用 `tag_namespace.validate_tag_compliance()`，会检查：

- 合法前缀和值域
- mandatory tags

batch 8 失败的具体非法标签包括：

- `func/结构`
- `func/关系`
- `genre/平台`

### 2.3 规则与文档存在漂移

当前代码的 `MANDATORY_PAIRS` 会对带任意 tag 的页面要求：

- `素材/ugc`
- `可信度/ugc`

但项目文档描述更接近：只有明确 UGC 来源时才强制这两个标签。必须先统一政策，否则流程和提示词会继续互相矛盾。

## 3. 推荐标签政策

建议采用以下语义：

- 普通知识页面：不自动添加 `素材/ugc`、`可信度/ugc`
- 明确来自公众号、论坛、自媒体、UGC、网页剪辑等来源：添加：
  - `素材/ugc`
  - `可信度/ugc`
- 明确来自书籍、官方资料等来源：使用对应的 `素材/*` 与 `可信度/*`
- 无法判断来源：不强行添加 UGC 标签，记录 warning

如果业务坚持“所有带 tag 页面都必须有 UGC 双标签”，则必须同步修改代码、文档、提示词和测试。本方案默认采用上面的来源语义，因为它与现有摄入规范更一致。

## 4. 唯一标签规范化器

以 `src/wiki/features/tag_namespace.py` 为唯一规则源，新增公共接口：

```python
normalize_tags(
    tags,
    *,
    source_kind=None,
    source_path=None,
) -> TagNormalizationResult
```

结果至少包含：

- `tags`: 最终合法标签
- `mapped`: 旧前缀/别名映射记录
- `removed`: 无法安全映射而删除的标签
- `warnings`: 需要人工关注的问题
- `mandatory_added`: 自动补充的 mandatory 标签

禁止在以下位置复制独立规则：

- `src/pipeline/generator.py`
- `src/pipeline/analyzer.py`
- `src/wiki/features/batch_gate.py`
- `scripts/cleanup_invalid_tags.py`
- CLI tags validate

### 4.1 Legacy 前缀映射

对可确定映射的旧标签转换：

| 旧前缀 | 新前缀 |
|---|---|
| `genre/` | `题材/` |
| `func/` | `功能/` |
| `char/` | `角色/` |
| `event/` | `事件/` |
| `mood/` | `情绪/` |
| `entity/` | `实体/` |
| `scene_phase/` | `场景阶段/` |
| `status/` | `状态/` |

无法安全映射的标签：

- 不猜测
- 从最终 tags 移除
- 记录 warning
- 写入 batch 审计报告

## 5. 执行任务

### Task 1：标签规范化契约

先写测试，再实现：

- legacy 前缀正确映射
- 合法中文标签保留
- 非法值删除并产生 warning
- 空标签不自动添加 UGC
- 明确 UGC 来源自动添加双标签
- 规范化结果幂等

### Task 2：Generator 输出后处理

统一 Generator 的 unified、legacy/two-step 页面构造路径：

```python
normalization = normalize_tags(
    raw_tags,
    source_kind=...,
    source_path=source_path,
)
page.tags = normalization.tags
```

同时保留规范化审计信息，不让原始非法标签进入 `WikiPage.tags`。

提示词继续保留并修正：

- 明确合法中文前缀和值域
- 明确禁止 `genre/func/...`
- 明确 UGC 来源的判断条件
- 普通来源不要无依据添加 UGC 标签
- 示例必须来自 `tag_namespace.py`

同步检查：

- `src/pipeline/analyzer.py`
- `src/pipeline/generator.py`
- `docs/reference/ingest-prompts.md`
- `docs/guides/novel-wiki-ingest-spec.md`

### Task 3：commit_ingest 统一兜底

在 `src/pipeline/ingest.py::commit_ingest()` 的 `write_page()` 前，对：

```python
pages + extra_pages
```

统一规范化。

覆盖：

- 新生成页面
- `extra_pages`
- 反向关系写盘
- batch 重试路径
- 其他经过 `commit_ingest()` 的入口

建议保持 `write_page()` 本身只做结构校验，不对任意手工编辑页面静默改写；业务摄入在 `commit_ingest()` 统一处理。

每次发生 mapping/removal/mandatory add，记录：

```text
page_id
source_path
action
original_tag
normalized_tag
```

日志不得包含 API Key 或其他凭据。

### Task 4：Gate 对齐

`src/wiki/features/batch_gate.py` 只调用统一规范化器/validator，不再自行解释标签规则。

Gate 输出区分：

- `TAG-MAPPED`: 自动映射，非阻断
- `TAG-REMOVED`: 删除无法映射标签，非阻断但需审计
- `TAG-MISSING-MANDATORY`: 明确来源要求但缺 mandatory，阻断
- `TAG-UNKNOWN`: 无法判断，按项目政策处理

`cleanup_invalid_tags.py` 也改为调用公共规范化器：

- dry-run 输出 mapping/removal/mandatory
- `--apply` 使用公共函数
- 保留 `--page-ids` 定向修复能力

### Task 5：修复 batch 8

当前 batch 8 的 20 个源文件均已处理成功，只有少数页面标签失败，不立即回滚。

先执行定向 dry-run：

```bash
PYTHONPATH=. python scripts/cleanup_invalid_tags.py \
  --root knowledge/novel-wiki \
  --page-ids <batch8受影响page_ids>
```

确认报告后 apply：

```bash
PYTHONPATH=. python scripts/cleanup_invalid_tags.py \
  --root knowledge/novel-wiki \
  --page-ids <batch8受影响page_ids> \
  --apply
```

然后只重新运行 batch 8 Gate re-check，不重新调用 LLM。Gate PASS 后才继续 batch 9。

### Task 6：继续后续批次

batch 8 Gate PASS 后：

```bash
PYTHONPATH=. python -m src.cli batch run \
  --root knowledge/novel-wiki \
  --batch 9 \
  --concurrency 3
```

每批完成后检查：

- `batch_build_state.json` 状态为 `committed`
- Gate 无 `TAG-ENUM`
- 无永久失败文件
- vector pending 数量可解释

## 6. 测试计划

### 6.1 规范化器测试

- `genre/玄幻 -> 题材/玄幻`
- `func/教程 -> 功能/教程`
- 非法值被移除并产生 warning
- 合法 tag 保留
- 无来源证据时不自动补 UGC
- UGC 来源自动补双标签
- 重复执行结果不变

### 6.2 Generator 测试

- LLM 输出 `func/结构` 不进入 `WikiPage.tags`
- LLM 输出 `genre/玄幻` 转成 `题材/玄幻`
- 生成结果通过 Gate

### 6.3 commit_ingest 测试

- `pages` 含非法标签时落盘后合法
- `extra_pages` 含非法标签时落盘后合法
- 规范化不会导致 AtomicContext 回滚
- warning 有审计记录

### 6.4 Gate 测试

- Gate 与写盘使用同一规则
- 可映射 legacy tag 不再阻断
- 明确 UGC 来源缺 mandatory 仍阻断
- 普通非 UGC 页面不因缺 UGC 双标签阻断

## 7. 回滚标准

出现以下任一情况，停止后续批次并回滚当前批次：

- 正文或非标签 frontmatter 损坏
- 合法标签被大面积误删
- UGC 判定错误导致大面积补错
- Gate 在同一规则下继续失败
- `batch_build_state` 与实际页面状态不一致

回滚命令：

```bash
PYTHONPATH=. python scripts/rollback_batch.py \
  --root knowledge/novel-wiki \
  --batch <N> \
  --yes
```

## 8. 最终成功标准

- Prompt、Generator、commit_ingest、extra_pages、Gate 共用同一标签规则
- batch 8 Gate re-check PASS
- 后续批次不再出现 `func/`、`genre/` 等 legacy tag
- 普通页面不无依据添加 UGC 标签
- 明确 UGC 来源页面具备 `素材/ugc + 可信度/ugc`
- 所有规范化操作可审计
- 相关测试通过
