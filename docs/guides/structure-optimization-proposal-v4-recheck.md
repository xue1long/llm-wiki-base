# "建议删除/暂缓"任务复核报告

> **复核日期**：2026-08-03
> **复核目的**：确认两个"建议删除/暂缓"任务的判断是否正确

---

## 一、任务 0.5：slugify 合并 — **确认暂缓**

### 原判断

> 函数签名/语义不一致，合并可能破坏决策页面 ID

### 复核结果

#### 1. 函数签名差异确认

```python
# decision._slugify
def _slugify(text: str, max_len: int = 40) -> str:  # 有 max_len 参数

# utils.slugify
def slugify(text) -> str:  # 无 max_len 参数
```

**差异**：`decision._slugify` 有截断参数 `max_len=40`，`utils.slugify` 无此参数。

#### 2. 实现逻辑差异确认

```python
# decision._slugify: 简单正则替换
slug = re.sub(r"\s+", "-", text.strip().lower())
slug = re.sub(r"[^a-z0-9\-一-鿿]", "", slug)
slug = re.sub(r"-{2,}", "-", slug)
if len(slug) > max_len:
    slug = slug[:max_len].rstrip("-")

# utils.slugify: 复杂的 run-based 处理
runs = _split_runs(text)  # 分割 ASCII/CJK/其他
for i, (kind, seg) in enumerate(runs):
    # 边界处理逻辑完全不同
    ...
```

**差异**：实现逻辑完全不同，可能产生不同输出。

#### 3. 使用场景分析

```python
# decision.py:172
slug = _slugify(question)  # 用于生成 decision 页面 ID
```

**关键**：`_slugify` 用于生成**决策记录页面的 ID**，这是持久化数据。

#### 4. 风险评估

| 场景 | 风险 |
|------|------|
| 直接替换为 `utils.slugify` | 可能产生不同的 slug，破坏已有决策页面的 ID 一致性 |
| 保留 `_slugify` 不修改 | 无风险，只是代码重复 |
| 删除 `knowledge/memory/` 整个目录 | 需要阶段 3 产品决策 |

#### 5. 结论

**✅ 确认暂缓是正确判断**

**理由**：
1. 两个函数语义不同（截断 vs 不截断）
2. `_slugify` 用于生成持久化数据的 ID
3. 冒险合并可能破坏数据一致性
4. 风险远大于收益（只是"代码重复"的整洁问题）

**建议**：等待阶段 3 决定是否删除整个 `knowledge/memory/` 目录。

---

## 二、任务 0.6：移动 test_helpers.py — **确认不建议执行**

### 原判断

> 需修改 11 个测试文件，风险大于收益

### 复核结果

#### 1. 影响范围确认

```bash
# 实际引用 test_helpers 的测试文件
tests/test_wiki/test_stubs_atomic.py
tests/test_wiki/test_stubs.py
tests/test_pipeline/test_retry.py (3 处引用)
tests/test_pipeline/test_pipeline.py
tests/test_pipeline/test_ingest_split.py
tests/test_pipeline/test_ingest_source_fallback_c4.py
tests/test_pipeline/test_ingest_generate_commit_split.py
tests/test_pipeline/test_generator.py
tests/test_pipeline/test_analyzer_json.py
tests/test_pipeline/test_analyzer.py
tests/test_lib/test_budgeted.py
```

**确认**：**11 个测试文件**需要修改导入路径。

#### 2. 收益分析

| 收益 | 描述 |
|------|------|
| 代码位置更合理 | `src/shared/test_helpers.py` → `tests/helpers/scripted_llm.py` |
| 符合测试辅助代码放 tests/ 的惯例 | 是 |

#### 3. 成本分析

| 成本 | 描述 |
|------|------|
| 修改 11 个文件 | 每个 1 行导入 |
| 更新文档示例（4 处 plans/*.md） | 可能被忽略 |
| 可能遗漏的引用 | 增加回归风险 |

#### 4. 风险评估

| 风险 | 级别 |
|------|------|
| 遗漏某个引用导致测试失败 | 中 |
| 文档示例代码过时 | 低 |
| 合并冲突（如果有其他分支） | 低 |

#### 5. 结论

**✅ 确认不建议执行是正确判断**

**理由**：
1. **收益仅为"代码位置更合理"**，无功能性改进
2. **成本涉及 11 个测试文件 + 4 处文档**
3. **风险**：遗漏引用会导致 `pytest` 失败
4. **收益/成本比 ≈ 0.1**

**建议**：
- **方案 A**：保留 `src/shared/test_helpers.py`，不做任何修改
- **方案 B**（如果必须清理）：在阶段 1 完成并验证后，作为独立 PR 执行，并确保全量测试通过

---

## 三、额外发现

### 发现 1：`knowledge/memory/` 被实际使用

```python
# src/mcp_server/memory_tools.py:373
decision_recorder: Optional ``DecisionRecorder`` instance.
```

MCP 服务器的 memory tools 接受 `DecisionRecorder` 参数，而 `DecisionRecorder` 在 `knowledge/memory/decision.py` 中定义。

**影响**：
- `knowledge/memory/` **不是纯粹的死代码**
- 它被设计为 MCP memory API 的一部分
- 虽然当前生产可能没有实际调用，但删除会破坏 API 完整性

**修正建议**：方案应在阶段 3 明确"保留并接线"或"标记为 experimental"。

### 发现 2：`_slugify` 在 `knowledge/memory/` 内部使用

```python
# decision.py:172
slug = _slugify(question)
```

如果未来要接线 `DecisionRecorder`，`_slugify` 是必需的。

**结论**：暂缓合并是正确判断，甚至应该考虑将 `utils.slugify` 的能力扩展以支持 `max_len` 参数。

---

## 四、最终结论

| 任务 | 原判断 | 复核结果 | 理由 |
|------|--------|----------|------|
| **slugify 合并** | 暂缓 | ✅ **确认暂缓** | 函数语义不同，用于持久化数据 ID，风险 > 收益 |
| **test_helpers 移动** | 不建议执行 | ✅ **确认不建议** | 收益仅为"代码位置更合理"，成本涉及 15+ 文件 |

---

## 五、修正建议

### 对方案 v4 的修正

无需修正，原判断正确。

### 补充说明

在阶段 3 的 KOS 组件裁决中，应明确：

1. `knowledge/memory/decision.py` 的 `DecisionRecorder` 被 MCP memory API 设计使用
2. 如果产品确认需要 memory API，则应**接线而非删除**
3. `_slugify` 应保留或统一（为 `utils.slugify` 增加 `max_len` 参数）