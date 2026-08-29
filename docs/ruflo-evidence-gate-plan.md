# 实施方案：在 candidate 生成路径接入写前证据闸

> 目标：复用 KC 的 `validate_evidence` / `verify_claim`，在 `KnowledgeCandidate`
> 进入页面生成与提交前，做零额外 LLM 调用的 source-level structural evidence 校验。
> 默认只标注结果，不删除页面；严格模式下整个 candidate 生成失败且不提交。
> 本方案不是完整的 claim truth gate：它不能证明引用在语义上蕴含或支持 claim。

本方案只针对真实运行时确认过的 candidate 路径。当前仓库的 `generate_ingest()`
仍包含 chunked、`unified_generate()` 和 legacy `generate()` 路径，且
`generate_from_candidate()` 的运行时调用者需要先确认。因此不能把“candidate 模式
是默认路径”当作前提。

---

## 0. 设计原则与非目标

| 决策 | 选择 | 说明 |
|---|---|---|
| 默认策略 | annotate | 证据失败的页面仍可读，但必须明确标为未验证 |
| 严格策略 | `RUFLO_EVIDENCE_STRICT=1` | candidate 级失败；不得调用 `commit_ingest` |
| LLM 调用 | 0 次新增 | 只验证 Analyzer 已给出的 quote |
| KC 复用 | 只调用公开的 `validate_evidence` / `verify_claim` | 不修改 KC 语义 |
| 证据粒度 | candidate/source 页 | 当前 generator 没有 page→claim 映射，不把整份报告错误复制到所有下游页 |
| 验证等级 | `anchored` → `structurally_verified` → `entailed` | 本方案最多产出 `structurally_verified`；`entailed` 只保留为后续人工/语义校验等级 |
| 跨 block quote | 不支持 | KC `Evidence` 要求单一 `block_id`；跨 block 直接视为未验证 |

非目标：本方案不负责把 legacy/unified 路径迁移成 candidate 路径，不新增证据抽取
LLM，不改 KC 合同，不建立新的证据存储表。

---

## 1. 前置取证：先锁定真实运行路径

编码前必须完成以下检查，并把结果写入实现提交的说明：

1. 搜索 `generate_from_candidate(` 的所有调用者；确认哪个入口由 HTTP ingest 实际触发。
2. 确认该入口收到的是 `KnowledgeCandidate`，而不是 `AnalysisResult`。
3. 确认 candidate 生成完成后调用 `commit_ingest()` 的位置。
4. 确认 strict 失败时可以在 `commit_ingest()` 之前返回错误，且不会产生磁盘写入。
5. 如果没有可达的 candidate 入口，本方案只能完成 gate 单元测试，不能宣称运行路径
   已接入；此时应先补一个独立的 candidate 路由任务。

当前已核实的接口约束：

- [candidate.py](../src/knowledge/core/candidate.py) 的 claim/evidence 是 opaque dict；
- Analyzer claim 使用 `statement`，不是 KC `verify_claim()` 所要求的 `text`；
- [generator.py](../src/pipeline/generator.py) 的 `generate()` 不接受
  `evidence_report`；
- [types.py](../src/wiki/core/types.py) 的 `WikiPage` 没有 `frontmatter` 属性，
  所以不能通过 `page.frontmatter[...]` 写字段。

---

## 2. 数据合同与适配

### 2.1 candidate claim → KC claim

在 gate 内部使用显式 adapter，不把两个 dict 合同直接混用：

```python
def to_kc_claim(candidate_id: str, index: int, claim: dict) -> dict:
    return {
        "id": f"{candidate_id}:{index}",
        "text": str(claim.get("statement", "")),
        "source": claim.get("source") or candidate_id,
    }
```

当 `statement` 为空时，该 claim 必须失败，不能依赖 `verify_claim()` 的异常来完成校验。

### 2.2 evidence_refs 的安全解析

只接受整数索引；字符串、浮点数、负数、越界值和非 list 值都转换为“无有效证据”，
并记录失败原因，不得抛出未处理的 `TypeError`。

### 2.3 验证结果与等级

```python
from typing import Literal

@dataclass
class ClaimVerification:
    claim_index: int
    statement: str
    evidence_indexes: tuple[int, ...]
    status: Literal["anchored", "structurally_verified", "entailed"]
    reason: str = ""

@dataclass
class VerificationReport:
    candidate_id: str
    total_claims: int
    anchored_claims: int
    structurally_verified_claims: int
    entailed_claims: int
    claims: list[ClaimVerification]
    structurally_verified_evidence: list[Evidence]
    strict: bool = False
```

`anchored` 表示 quote 可以在指定 source 的单一 block 中定位；
`structurally_verified` 表示 quote 通过 KC 的结构校验和 `verify_claim()`；
`entailed` 表示 quote 在语义上支持 claim，本方案不产生此等级，默认值为 0。
`structurally_verified_evidence` 按 `(document_id, block_id, quote_hash)` 去重。报告必须保留
claim 与 evidence 的关系，不能只有 candidate 级的总比例。

---

## 3. `src/pipeline/evidence_gate.py`

### 3.1 定位规则

```python
def locate_block(document, quote: str) -> str | None:
    if not isinstance(quote, str) or len(quote.strip()) < 20:
        return None
    for block in document.blocks:
        if quote in block.content:
            return block.block_id
    return None
```

`normalize_text()` 会统一换行、去除行尾空格并裁剪首尾空白。gate 必须使用同一份
canonical source text 生成 `document`，并在定位前对 quote 应用同样的最小规范化；不能
用原始 source text 生成 quote、再用另一种文本生成 block。短于 20 个 Unicode 字符的
quote 默认拒绝，以避免“研究表明”“增长 23%”等常见短语伪造证据锚点。

跨 `\n\n` 的 quote 没有单一 `block_id`，直接记为 `cross_block_quote` 失败；本阶段不
伪造 block id。

### 3.2 gate 流程

对每个 claim：

1. 安全解析 `evidence_refs`；
2. 校验每条 evidence 的 `source_path` 与 candidate 的 canonical source identity 一致；
3. 对来源一致的 evidence 定位 block；
4. 调用 `validate_evidence()`；任何失败只影响该 claim；
5. 用 `to_kc_claim()` 转换 claim 后调用 `verify_claim()`；
6. 写入 `ClaimVerification`，保留明确失败原因和等级。

`source_path` 比较必须统一路径分隔符、大小写和相对/绝对路径表示，但不能只比较
文件名。来源不一致记为 `source_mismatch`，不得因为 quote 恰好相同而通过。

严格模式不在 gate 内半途抛出。gate 完成后由调用方依据报告决定：

```text
strict && structurally_verified_claims != total_claims
→ abort candidate
→ 不调用 commit_ingest
→ 返回/记录 candidate_id、失败 claim、失败原因
```

这样可以保证失败语义与写入边界清晰，也避免部分验证结果导致半写入。

---

## 4. 页面标注与持久化

### 4.1 `WikiPage` 字段

新增正式字段，不使用不存在的 `page.frontmatter`：

```python
evidence_anchored_claims: int = 0
evidence_structurally_verified_claims: int = 0
evidence_entailed_claims: int = 0
evidence_total_claims: int = 0
evidence_state: str = "unverified"  # unverified | anchored | structurally_verified | entailed | partial
```

同步修改：

- `WikiPage.to_frontmatter_dict()`；
- `WikiPage.from_dict()`，对旧页面使用默认值；
- wiki spec 和相关 dataclass 测试。

落盘格式：

```yaml
evidence_anchored_claims: 4
evidence_structurally_verified_claims: 3
evidence_entailed_claims: 0
evidence_total_claims: 4
evidence_state: structurally_verified
```

### 4.2 标注范围

当前 generator 没有 page→claim 映射，因此只给本次 candidate 的 source 页追加：

```markdown
## 证据溯源
> 原文（<block_id>）："<quote>"
```

非 source 页暂不复制 candidate 级证据，避免错误归因。若未来要求实体/概念页也有
句级证据，必须先让 generator 输出每页的 claim indexes，再扩展本方案。

### 4.3 插入点

gate 必须位于真实 candidate caller 中，顺序固定为：

```text
Analyzer → KnowledgeCandidate
        → evidence_gate
        → generate_from_candidate
        → annotate source page
        → commit_ingest
```

不要向 legacy `generate()` 盲目传入 `evidence_report`。若选择在
`generate_from_candidate()` 内标注，应给该函数增加明确的可选 report 参数，并为直接
调用者提供默认 `None`；若选择在 caller 标注，则保持 generator API 不变。两者只能选一种。

---

## 5. TDD 实施步骤

每一步先写失败测试，再实现并回归：

| 步骤 | 内容 | 必须验证 |
|---|---|---|
| T0 | 运行路径取证 | 找到真实 candidate caller；找不到则停止运行路径实施 |
| T1 | `locate_block` | 命中 block、空 quote、跨 block、CRLF/尾空格规范化 |
| T2 | claim adapter | `statement` 正确转换成 KC 所需 `id/text/source` |
| T3 | 正常 gate | 2 claim/2 evidence 全部 `structurally_verified`，claim→evidence 关系正确 |
| T4 | 部分失败 | 伪造 quote、短 quote、source_path 不一致、空 refs、越界 refs、非法 refs 类型均只标记对应 claim |
| T5 | 重复证据 | 多 claim 引用同一 evidence 时落盘只出现一份 quote |
| T6 | WikiPage round-trip | 新字段写入 YAML，读取旧页面有默认值，读写后值保持一致 |
| T7 | 页面标注 | 只标注 source 页，非 source 页不复制 candidate 级证据 |
| T8 | strict atomicity | strict 失败时 `commit_ingest` 不被调用，wiki/index/log 无新增写入 |
| T9 | 真实 candidate 路径 | 从实际入口摄取 fixture，断言 gate 被调用且页面包含正确证据字段 |
| T10 | legacy/unified 回归 | 非 candidate 路径行为不变，不出现 `evidence_*` 字段或参数错误 |

---

## 6. 验证命令

```powershell
$env:PYTHONPATH='.'
python -m pytest tests/test_pipeline/test_evidence_gate.py -v
python -m pytest tests/test_pipeline/ -v --import-mode=importlib
```

运行路径测试必须使用临时 project root 和 fake provider，不依赖外部 LLM。测试应
检查文件内容和 `WikiPage.from_dict()` 结果，不能只用 `grep` 判断。

完成 candidate 路径接线后，再做服务 smoke test，并记录 candidate caller、gate 调用次数、
candidate_id、anchored/structurally_verified/entailed、写入页面路径。

---

## 7. 风险与回滚

| 风险 | 防护 |
|---|---|
| candidate 路径不可达 | T0 阻断；不得宣称已生效 |
| quote 与 canonical text 不一致 | 统一 sanitizer/normalize 输入并覆盖测试 |
| KC claim 合同变化 | adapter 单测失败即阻断；不直接传 opaque claim |
| strict 误伤 | 默认关闭；strict 失败在 commit 前终止 |
| 页面字段破坏旧页 | `from_dict()` 使用默认值，增加 round-trip 测试 |
| 下游页面错误归因 | 当前只标 source 页；扩展前先建立 page→claim 映射 |
| 新增参数破坏 legacy 调用者 | 只修改已确认的 candidate caller，或使用默认值兼容 |

回滚只需移除 candidate caller 的 gate 调用和页面标注字段；KC 模块不修改，legacy
路径不受影响。

---

## 8. 完成标准

只有同时满足以下条件，方案才算完成：

1. T0 已确认真实 candidate 运行路径，并有测试覆盖；
2. 所有 claim 经过 adapter 后再调用 `verify_claim()`；
3. `WikiPage` 新字段可以可靠 round-trip；
4. strict 失败不会调用 `commit_ingest()`；
5. quote、refs、跨 block、重复 evidence 的异常测试全部通过；
6. legacy/unified 路径无参数错误且行为无回归；
7. 运行路径产生的 `anchored` / `structurally_verified` 证据能通过
   `source identity + block_id + quote` 在 canonical source 中复核。
8. 文档和页面状态明确声明：本方案不产出 `entailed`，也不是完整的 claim truth gate。

在满足以上条件前，不得使用“闸已生效”作为验收结论。
