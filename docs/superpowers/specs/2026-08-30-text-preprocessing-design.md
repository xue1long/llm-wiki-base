# Text Preprocessing Submodule Design

**Status:** Revised after first-principles, critical-thinking, and end-state review

## Goal

将 raw 文档摄取前的文本清洗、证据规范化和质量检测整理为一个独立、可审计的文本预处理模块，同时保持现有 Analyzer、Reviewer、Generator 和 pilot 的兼容性。

本设计的不可破坏约束：

1. 证据只绑定 `canonical_text`，不绑定 prompt 展示文本。
2. 每个模型可见 block 必须携带并映射到唯一的 canonical `source_id + block_id`。
3. prompt 去噪不得合并、拆分或改写可引用正文；无法建立映射时直接失败。
4. 新 preprocessing/block ID 版本不得让旧 bundle 和 evidence 静默失效。

## Problem

当前 `src/pipeline/sanitizer.py` 同时负责质量检测和文本变换，`src/pipeline/_pipeline_common.py` 另有一套 source page 去噪函数。candidate pipeline 将 sanitizer 输出直接用于 Analyzer 和 evidence block 生成，因此任何删除正文的清洗规则都会改变证据身份。现有 `normalize_text()` 还会执行自己的换行、行尾空白和首尾空白规范化；新模块必须统一这套规则，不能形成第二个隐式 canonicalizer。

本次 GLM5.2 pilot 已证明严格 evidence binding 可以工作，但长文档仍会产生模型截断，重复内容也会触发质量 warning。文本预处理需要明确区分：证据事实的唯一基准、模型提示视图和质量审计信息。

## Design

新增独立包：

```text
src/pipeline/text_preprocessing/
├── __init__.py
├── api.py
└── types.py
```

`api.py` 是唯一运行时入口，`types.py` 提供跨模块数据类型；规则实现保持在该包内部，不允许 Analyzer、Reviewer 或 Generator 直接导入规则细节。

对外接口：

```python
def preprocess_source(
    source_text: str,
    *,
    source_id: str = "",
    source_bytes_sha256: str | None = None,
    skip_llm_on_degraded: bool = False,
) -> PreprocessResult:
    """Return evidence-preserving canonical text, prompt text, and audit data."""
```

返回值：

```python
@dataclass(frozen=True)
class PreprocessResult:
    canonical_text: str
    canonical_document: CanonicalDocument
    prompt_text: str
    prompt_blocks: tuple[PromptBlockView, ...]
    report: NoiseReport
```

```python
@dataclass(frozen=True)
class PromptBlockView:
    source_id: str
    block_id: str
    ordinal: int
    prompt_content: str
    removed_line_count: int
```

`canonical_document` 是 Reviewer 和 replay 的唯一文档对象；`prompt_blocks` 是 Analyzer 的权威输入；
`prompt_text` 只是按原顺序拼接这些 block 的展示字符串。`PromptBlockView.block_id` 必须来自
canonical document，不能由 prompt 文本重新计算。

```python
@dataclass(frozen=True)
class NoiseReport:
    version: str
    source_bytes_sha256: str | None
    input_text_sha256: str
    canonical_text_sha256: str
    prompt_text_sha256: str
    quality_score: float
    warnings: tuple[str, ...]
    should_skip_llm: bool
    metrics_scope: str
    source_chars: int
    canonical_chars: int
    prompt_chars: int
    removed_line_count: int
    removed_char_count: int
    applied_rules: tuple[RuleApplication, ...]
```

```python
@dataclass(frozen=True)
class RuleApplication:
    rule_id: str
    removed_line_count: int
    removed_char_count: int
```

## Text layers

### canonical_text

这是证据唯一基准。允许的变换仅限于可确定、可重算的表示规范化：

- CRLF/CR 统一为 LF；
- Unicode NFC 规范化；
- 统一处理文件开头 BOM；
- 保留所有正文行、重复行、平台元数据和原始段落内容；
- 不进行语义删除、摘要、模糊替换或模型判断。

这里的“保留”不表示与原始字节逐字节相同：换行、NFC 和 BOM 是版本化的表示规范化，
因此必须同时记录规范化前后的身份：`source_bytes_sha256`（Collector 能拿到原始字节时）
或 `input_text_sha256`，以及 `canonical_text_sha256`。不能把 canonical hash 当作原始文件
hash，也不能用未经记录的额外 trim、大小写转换或 Unicode 替换。

规范化规则必须复用或明确替换现有 `normalize_text()` 的规则；禁止在 Reviewer、replay
或新模块外再出现第二套隐式规范化。规范化完成后只构建一次 `CanonicalDocument`：它保留
canonical 原文，并按确定的行/段边界生成唯一的 `source_id + block_id`。`block_id`、
`quote_hash`、`CandidateReviewer` 和独立 replay 都只基于这个对象。

### prompt_text

这是给 Analyzer/Generator 的输入视图。它可以在 canonical text 之上执行确定性结构去噪：

- 完整行精确匹配的平台按钮和页面 chrome；
- 明确格式的下载时间、修改时间和来源元数据；
- Feishu 导出标题伪影；
- 多余空行压缩；
- 重复行默认只告警，不删除；除非该行同时命中已登记的结构噪声规则。

Analyzer 的实际输入不是一个无法追溯的裸字符串，而是带 registry 的
`PromptBlockView[]`：每个 prompt block 与一个 canonical block 一对一对应，顺序不变，
不得合并、拆分或改写可引用正文。`prompt_text` 只是这些 block 的展示拼接结果，不能
重新计算 block_id，也不能成为 evidence 的替代基准。

每一次删除必须由可审计的规则完整行匹配，并累计到 `removed_line_count`、
`removed_char_count` 和 `RuleApplication`。如果某个视图变换无法证明 prompt block
仍对应唯一 canonical block，预处理直接失败。模型从 prompt block 看到的 quote 仍须是
对应 canonical block 的原文子串；不能用跨 block 拼接、模糊匹配或静默改写弥补映射。
Analyzer 声明的 evidence block 还必须存在于本次 prompt registry；只存在于 canonical
而被 prompt 视图隐藏的 block 不得被 candidate path 引用，否则 Reviewer 以
`evidence_block_not_visible` 拒绝。

### quality report

质量分和 warning 是观测结果，不等同于内容删除。当前的乱码比例、空行比例和重复比例规则继续保留；
指标默认覆盖完整输入文本，并通过 `metrics_scope="full_input_text"` 明确记录。若为性能原因
采用采样，必须记录采样范围和上限，不能把局部指标伪装成全文结论。`applied_rules` 记录每条
规则的实际命中及删除计数，而不是只记录汇总数字。

严重退化文本是否跳过 LLM 由调用方显式传入 `skip_llm_on_degraded=True` 决定。旧环境变量
只允许在 ingest 边界转换成这个显式参数，不得在预处理模块内部读取环境变量。默认行为仍是
记录 warning 并继续，由后续严格结构校验决定是否接受。

## Pipeline integration

`generate_ingest()` 只调用一次 `preprocess_source()`：

```text
raw source
  → preprocess_source
      ├─ canonical_text → canonical document → block_id / evidence validation
      ├─ prompt_blocks  → Analyzer (带 block registry) / Generator
      └─ report         → triage / pilot audit / diagnostics
```

Collector 在可用时提供 `source_bytes_sha256` 和外部确定的 `source_id`。candidate path 要求
Analyzer 收到带 `source_id`、`block_id`、ordinal、prompt_content 的渲染 block registry；
Reviewer 使用同一次预处理产生的 canonical_text 构建 `CanonicalDocument`，并拒绝 registry
与 canonical block 不一致的结果。legacy path 也复用同一个预处理结果，不再各自调用不同的
清洗实现。pipeline 不提供 `source_id` 时在进入 Analyzer 前失败，而不是生成临时 ID。

`prompt_text` 可以继续作为 Generator 的展示输入，但 Analyzer 的证据任务必须使用带 ID 的
block 格式；裸 `prompt_text` 只允许用于不产生 evidence 的兼容路径。

现有 `sanitize()`、`denoise_source_text()` 和 `clean_source_text()` 暂时保留为兼容包装函数，内部转调新模块；迁移完成前不得删除旧入口。

## Evidence and audit contract

每条成功 pilot 记录继续保留：

```json
{
  "source_id": "raw/sources/example.md",
  "block_id": "block_...",
  "quote_hash": "...",
  "binding_mode": "explicit_block_binding",
  "evidence_refs": ["evidence_..."],
  "exact_quote": "..."
}
```

并增加：

```json
{
  "preprocessing_version": "text-preprocess-v1",
  "source_bytes_sha256": "...",
  "input_text_sha256": "...",
  "canonical_text_sha256": "...",
  "prompt_text_sha256": "...",
  "noise_warnings": ["high_repetition"],
  "applied_rules": [
    {"rule_id": "blank_line_compression", "removed_line_count": 4, "removed_char_count": 4}
  ]
}
```

成功和失败记录都必须保留上述预处理字段、`binding_mode`、`failure_reason`（失败时）以及
可用的异常 cause chain。任何 canonical hash、source_id、block_id、quote 或 quote_hash
不一致都必须失败并保留原因；不得通过重新定位 quote、fuzzy matching 或静默重算报告来修复。

## Long-document handling

candidate path 对超过单次提示上限的 prompt blocks 按 canonical block 边界分块。每个 chunk
携带原始 `source_id`、稳定 `block_id`、chunk 序号和 preprocessing hash；chunk 之间不得
合并正文，也不得生成新的推断 block_id。

如果单个 canonical block 超过提示上限，v1 直接以 `oversized_canonical_block` 拒绝；
不得在 prompt 层硬切，因为派生 block ID 还必须同步进入 canonical document 并记录精确的
parent ID/行范围。待 canonical range 合同单独落地后，才允许按确定的行边界生成
`<parent_block_id>:part:<ordinal>`。任一 chunk 截断、解析失败或 evidence 映射失败，整个
source 不得部分发布，必须保留失败原因和已完成 chunk 状态以供审计/重放。

### Legacy compatibility

旧 bundle/report 使用的 block ID 和旧 sanitizer 结果不能被新模块静默重写。兼容读取路径标记
为 `legacy-sanitizer-v0`；新写入统一标记为 `text-preprocess-v1`。旧 evidence 继续按其
原始版本验证，无法验证时进入 quarantine 并报告原因；只有显式迁移命令才可生成新版本，且
迁移必须保留旧 hash、旧 block_id 和原始失败记录。

## Migration and testing

按以下顺序实施，每一步先写失败测试、再实现、再运行目标测试并单独提交：

1. `types.py` 和 `preprocess_source()` 的 canonical/prompt/report 单元测试；
2. 重复行、平台 chrome、frontmatter、乱码、空白和统计范围测试；
3. 旧 `sanitize()`/`denoise_source_text()` 兼容测试；
4. Analyzer 使用 prompt_text、Reviewer 使用 canonical_text 的 pipeline 测试；
5. block_id、quote_hash、source_id 和 replay 测试；
6. 确定性、canonical 内容保留、prompt block 一对一映射、输入/canonical hash 区分和旧版本兼容测试；
7. 长文档分块、超大 block fail-closed、preprocessing hash 传递、截断失败链及禁止部分发布测试；
8. pilot 审计字段与失败保留测试；
9. KC、pipeline、server 和全仓验证。

验收条件：

- canonical_text 不因重复行或平台去噪丢失正文；
- canonical_text 的输入 hash、规范化 hash、prompt hash 和 preprocessing version 可重算且含义不混淆；
- 每个 Analyzer prompt block 能一对一回到 canonical block，且所有 accepted evidence 可独立 replay；
- 所有 accepted evidence 可独立 replay；
- false accepts 为 0；
- 显式错误 block_id 永不回退到其他 block；
- 任一 chunk 失败不会产生部分发布；
- 旧版本 bundle/evidence 不会被静默改写或误判为新版本；
- 所有删除和 warning 可审计；
- 原始 `knowledge/novel-wiki` 不被读取、复制、写入或清理；
- 不新增 provider，不修改 MiniMax 配额或配置。

## Deliberate non-goals

- 不使用 LLM 判断噪声；
- 不在本次整理中重构 Collector 或 Wiki Writer；
- 不把 source page 的展示清洗误当作 evidence canonicalization；
- 不为提高 pilot 成功率而降低 fail-closed 标准。

## Frozen readiness vocabulary

The cross-format readiness layer uses the following versioned vocabulary. The
manifest in `tests/fixtures/content_readiness/golden.json` is the executable
contract for these values.

- `content_kind`: `prose`, `title_definition`, `table`, `list`, `code`,
  `image_ocr`, `mixed`, or `unknown`.
- `decision`: `ready`, `ready_with_warning`, `route_specialist`,
  `skip_no_content`, `quarantine_degraded`, or `unsupported`.
- `reason_codes`: `empty_input`, `metadata_only`, `duplicated_navigation`,
  `no_evidence_capacity`, `legitimate_short`, `high_repetition`,
  `encoding_degraded`, `ocr_degraded`, `missing_provenance`,
  `unsupported_format`, `oversized_block`, `empty_subblock`,
  `specialist_failed`, or `policy_violation`.

`metadata_only` is a reason code, never a content kind. New audit records use
the `decision` key; `readiness_decision` is not an alias. Unknown values are
contract errors and must fail closed rather than being silently coerced.
