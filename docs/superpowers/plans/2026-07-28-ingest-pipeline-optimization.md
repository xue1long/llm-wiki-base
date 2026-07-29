# Ingest Pipeline 速度优化方案

## 现状

每个文件摄入需要 **2 次串行 LLM 调用**（Analyzer → Generator），总耗时 15-45s/文件。

```
源文本 → Analyzer(分析提取) → 中间JSON → Generator(填充slot) → WikiPage列表
          ~5-15s                              ~10-30s
```

## 优化 1：合并 Analyzer + Generator（核心）

### 动机

Analyzer 的中间 JSON（`AnalysisResult`）只被 Generator 消费，人类从不阅读。两步分离造成：
- 信息瓶颈：Analyzer 提取的 entity 可能被 Generator 跳过
- Slug 漂移：Analyzer 给 slug `zongcai-wen`，Generator 可能改成 `zong-cai-wen`
- 双倍延迟：两次网络往返 + 两次 LLM 推理

### 方案

合并为一个 `unified_generate` 调用，直接从源文本输出 WikiPage 列表。

**输入**：源文本 + 已有 wiki 索引 + 页面模板 + 规则  
**输出**：`{pages: [{id, type, title, slots, relations, tags}]}`

保留现有代码中的 Fix D（source page）、Fix E（stub）、relation 去重、wikilink 修正——这些是代码层逻辑，不依赖 LLM。

### 预期效果

- 速度：**~50% 提升**（1 次 LLM 调用代替 2 次）
- 质量：LLM 看到完整任务上下文 → entity 不再丢失
- 成本：1 次长调用 vs 2 次中等调用，token 消耗接近

### 风险

- prompt 更长更复杂 → 对弱模型（MiniMax 等）可能不稳定
- 需要保留 Analyzer 作为 fallback（两步模式），通过参数切换

---

## 优化 2：并行批量摄入

### 动机

多个 raw 文件之间完全独立，可以并发处理。

### 方案

在 `ingest.py` 中增加 `run_batch_ingest()` 函数，接受文件列表：

```python
async def run_batch_ingest(paths, files, provider, concurrency=3):
    sem = asyncio.Semaphore(concurrency)
    async def ingest_one(f):
        async with sem:
            return await run_ingest(paths, f, ...)
    return await asyncio.gather(*[ingest_one(f) for f in files])
```

`concurrency=3` 平衡速度和 LLM rate limit。

### 预期效果

- 速度：**~3x 提升**（3 并发，受 rate limit 约束）
- 质量：无影响（文件独立）

### 风险

- 需要 LLM provider 支持并发请求
- 同时写入 wiki 需要 AtomicContext 处理并发

---

## 优化 3：精简 Prompt

### 动机

Generator prompt 约 190 行，存在大量重复：
- Language 指令出现 2 次
- Relation types 完整列表（17 种）
- 多项 "do NOT" 警告可合并

### 方案

- 去重：Language 只写一次
- 压缩：Relation types 缩写为 `is_part_of/contains/references/...`
- 合并：多个 "do NOT" → 一个简洁的约束段

### 预期效果

- 速度：**~15% 提升**（减少输入 token）
- 质量：无影响

---

## 实施顺序

| 阶段 | 内容 | 预计改动文件 |
|---|---|---|
| **Phase 1** | 优化 3：精简 Prompt | `generator.py`（只改 prompt 字符串） |
| **Phase 2** | 优化 1：合并 Analyzer + Generator | `generator.py`（新增 `unified_generate`）、`ingest.py`（参数切换） |
| **Phase 3** | 优化 2：并行批量摄入 | `ingest.py`（新增 `run_batch_ingest`）、`services/ingest.py` |

建议先做 Phase 1+2，10 个文件摄入预计从 2.5-7.5 分钟降到 **1-3 分钟**。
