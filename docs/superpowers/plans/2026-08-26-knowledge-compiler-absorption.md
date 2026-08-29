# Plan: 从 Knowledge Compiler 规范吸收三类能力（C→A→B 三段迁移）

- **status**: pending — 待 plan-audit 两轮 + 人工复核后开工
- **branch**: feature/2026-08-26-knowledge-compiler-absorption
- **关联 ADR**: `docs/adr/2026-08-26-knowledge-compiler-absorption.md`（待写）
- **参考 plan**:
  - `docs/superpowers/plans/2026-08-19-llm-kb-design-absorption.md`（TDD-per-task + 决策表 + 架构整改说明格式参考）
  - `docs/superpowers/plans/2026-08-26-module-standardization-unification.md`（B 阶段"模块归一"思路参考）
- **源规范**: `007 - 个人笔记/000 Inbox/2026-08-21 Knowledge Compiler.md`（非仓库文件，不入库）
- **阶段策略**: **C 先适配 → A 严纪律 → B 再归一**。每段独立可发布、可回滚；不要三段一起做。

---

## 总览：三段纪律

> **核心思路：先治"债务"再定"规矩"，最后才"统一"。**

```
┌─────────────────────────────────────────────────────────────┐
│  C 适配落地（Phase C）                                       │
│  ─────────────────────────────────────────                  │
│  目标：剥离 Knowledge Compiler 带来的耦合与债务；              │
│        做最小适配层让现有代码能"接收"KC 概念；                  │
│        植入最小能力让架构能 verify 得住                        │
│  思想："先能跑，先能测，先能查"                                │
├─────────────────────────────────────────────────────────────┤
│  A 纪律优先（Phase A）                                       │
│  ─────────────────────────────────────────                  │
│  目标：定命名、定目录、定入参出参、定依赖引入规范；               │
│        让新加的功能"不会再次污染"                              │
│  思想："先立规矩，后做事"                                      │
├─────────────────────────────────────────────────────────────┤
│  B 归一（Phase B）                                           │
│  ─────────────────────────────────────────                  │
│  目标：全量架构统一、模块彻底归一、择机落地                     │
│  思想："先分散探索，最后归一"                                  │
└─────────────────────────────────────────────────────────────┘
```

### 三段关系（关键）

| 段 | 作用 | 不做会怎样 |
|---|---|---|
| **C 适配** | 解决"现在已经有耦合/债务怎么办" | 后续每写一行就要还债，债务永远还不清 |
| **A 纪律** | 解决"以后怎么写才不会再欠债" | 没有规矩，加新能力会复现历史错误 |
| **B 归一** | 解决"功能都搬完之后怎么统一" | 模块会越来越分裂，归一成本随时间指数上升 |

> ⚠️ **顺序不可颠倒**：
> - 跳过 C 直接 A → 在污染的代码上立规矩，规矩会和现实冲突，最后废弃
> - 跳过 A 直接 B → 归一过程中每改一个文件都触发风格争论，无人推进
> - 跳过 C+A 直接 B → 大爆炸式重写，几乎必失败

---

## Goal

按 C→A→B 三段纪律，把 `2026-08-21 Knowledge Compiler.md` 50 节规范中**有结构性价值**的能力迁入 ruflo-kb：

**结构性价值（必迁）**——属于"AI 知识库最根本的能力差距"：
1. **Evidence 一等公民**（KC §15）——反幻觉的锚点
2. **Knowledge Diff**（KC §35）——Agent 增量同步
3. **Superseded-by 关系**（KC §34）——可演化的基础
4. **Manifest + Protocol 接缝**（KC §7-§8）——可替换的地基
5. **Policy Engine**（KC §28）——判定集中化

**工程优化（不迁）**——ruflo-kb 已具备或与本项目哲学冲突：
- 完整 Plugin Manager 生命周期（C 级，存档）
- YAML Workflow 解释器（与 ponytail 极简冲突）
- 自动 Tag Proposal（当前 `tags validate` 已够用）
- 入库评分（8 维 → 4 档，与现有 `quality_settings.json` 冲突先不迁）

### 非目标（明确划界）

- 不做 Plugin Marketplace / SDK / 多租户 / Dashboard（C 级，禁止）
- 不做 YAML Workflow loader（DAG 引擎属于过度工程）
- 不做 Faithfulness Score 默认开启（增加 LLM 调用 = 增加 token 成本）
- 不动现有 `WikiPage.sources` 字段（保留作向后兼容回退）
- 不动现有 `LifecycleState.DEPRECATED` enum 名（兼容存量）
- 不动现有 `tag_namespace.py` 12 个 prefix（P1 之后动作）
- 不动 capture 模板与 short-form 集成（2026-08-19 plan 已收口）
- 不动 `ReviewerStage` 4 规则（新增 Faithfulness 是可选 LLM stage，OFF by default）

---

## 三段任务对应表（速查）

| 段 | 任务 ID | 主题 | 优先级 |
|---|---|---|---|
| **C 适配** | T-C1 | 剥离 KC 与 ruflo-kb 的命名/概念债务 | 🔴 |
| **C 适配** | T-C2 | 最小 Evidence 适配层（不重写） | 🔴 |
| **C 适配** | T-C3 | 最小 Protocol 接缝（仅 LLM + Parser） | 🔴 |
| **C 适配** | T-C4 | Policy Engine 最小可用版（只搬判定，不加规则） | 🔴 |
| **A 纪律** | T-A1 | 命名/目录/契约/依赖 4 类规范定稿并 DOC 化 | 🔴 |
| **A 纪律** | T-A2 | CI 守门：pre-commit 钩子 + ruff/mypy 引入（可选） | 🟡 |
| **A 纪律** | T-A3 | Doc registry：本次新增 5 个模块必须进 `docs/` 子表 | 🟡 |
| **B 归一** | T-B1 | Evidence 一等公民 dataclass + 持久化目录 | 🟡 |
| **B 归一** | T-B2 | Knowledge Diff 工具 + CLI | 🟡 |
| **B 归一** | T-B3 | Superseded-by 关系 + 状态机扩展 | 🟡 |
| **B 归一** | T-B4 | 全量架构复审：Manifest 升级为通用 Plugin Manifest | 🟢 |

> 🔴 4 个 | 🟡 6 个 | 🟢 1 个

---

## 阶段 C：适配落地（先做这段）

> **核心动作**：把"KC 已经说过的概念"通过最小改造塞进现有 ruflo-kb，**不重写任何业务逻辑**。本阶段产物：能跑、能测、能查、能追溯。

### C 阶段总目标（验收）

- [ ] 现有 1163 个测试无回归
- [ ] Evidence 可以被 LLM/Agent 通过稳定 API 查到（虽然还是 frontmatter 附属字段）
- [ ] `KnowledgeObject` 可以计算与上一版的 Diff（虽然输出只写到日志）
- [ ] LLM Provider 可以表达自身 healthcheck 状态
- [ ] Parser 走 `ParserRegistry.discover()` 而不是写死的 if-elif

---

### Task T-C1：KC 与 ruflo-kb 的概念债务剥离

> **为什么必做**：KC 提到 `Knowledge Object / Evidence / Wiki / Capability / Plugin / Contract`，这些名词在 ruflo-kb 里**已经存在但叫法不一致**（`WikiPage` ≈ `Knowledge Object`、`sources` ≈ `Evidence 弱版本`）。如果不剥离债，后面所有任务都要带"翻译层"工作量。

#### T-C1.1 建立 Glossary 映射表

- **Files**:
  - `docs/architecture/glossary-kc-mapping.md`（新文件）
- **实现**: 一张表，每行 = 一个 KC 概念 + ruflo-kb 等价物 + 差异 + 后续任务
- **关键不变量**:
  - **禁止**改任何现有 dataclass 名字（避免大范围 import 重写）
  - 仅在新代码里使用 KC 命名，旧代码用兼容别名
- **Acceptance**: 文件存在；表头包含 `KC 概念 | ruflo-kb 等价 | 差异 | 处理方式`；commit `feat(docs): glossary-kc-mapping`

#### T-C1.2 项目级 ADR

- **Files**:
  - `docs/adr/2026-08-26-knowledge-compiler-absorption.md`（新文件，照 2026-08-19 模板）
- **必填字段**:
  - 上下文：KC 50 节，择优吸收
  - 决策：C→A→B 三段纪律
  - 三段各自阶段目标
  - 显式不吸收项
- **Acceptance**: ADR 文件存在；可被 `code-review` skill 读出后无歧义；commit `docs(adr): kc-absorption-decision`

---

### Task T-C2：最小 Evidence 适配层

> **为什么必做**：P1-1（Evidence 一等公民）是大改造；本阶段先做"API 适配层"，让 Evidence 作为概念可用，但不重写持久化。

#### T-C2.1 Evidence dataclass + 适配器

- **Files**:
  - `src/knowledge/evidence/shim.py`（新文件，含 `Evidence` dataclass + `EvidenceAdapter.from_wiki_page()`）
  - `tests/test_knowledge/test_evidence_shim.py`（新文件，5 测试）
- **实现**:
  ```python
  @dataclass
  class Evidence:
      """KC §15 Evidence 模型 — 仅 dataclass 形式，不动持久化."""
      evidence_id: str
      source_document_id: str
      quote: str = ""
      quote_hash: str = ""        # SHA256 前 16 hex
      confidence: float = 0.0
      supports_claim_id: str | None = None  # 留空，Phase B 填

  class EvidenceAdapter:
      """Phase C 适配器：把现有 WikiPage.sources 字段映射成 Evidence 列表."""
      @staticmethod
      def from_wiki_page(page: WikiPage) -> list[Evidence]:
          # 占位实现：每条 source 字符串 → Evidence.source_document_id
          ...
  ```
- **不动**:
  - `WikiPage` dataclass
  - frontmatter 序列化逻辑
  - `Provenance` dataclass
- **TDD**:
  1. `Evidence.from_quote(quote)` 计算 `quote_hash` 用 SHA256 前 16 hex
  2. `EvidenceAdapter.from_wiki_page()` 返回 list 长度 = `len(page.sources)`
  3. 当 `page.sources = []` 时返回空 list 而非 None
  4. 当 source 是绝对路径时，`source_document_id = Path(source).stem`
  5. `evidence.evidence_id` 默认 = `f"ev_{quote_hash[:12]}"` 当 quote 非空
- **Acceptance**: 5 测试全过；存量 WikiPage 单测无回归；commit `feat(evidence): shim + adapter`

#### T-C2.2 写一个独立查询入口（不接 Agent）

- **Files**:
  - `src/knowledge/evidence/query.py`（新文件，纯函数 `get_evidence_for_page(page_id, project)`）
  - `tests/test_knowledge/test_evidence_query.py`（新文件，3 测试）
- **约束**:
  - **读**现有 wiki 页面（用现有 reader，**不**新建 reader）
  - **返回** `Evidence` list（用 C2.1 dataclass）
  - 失败 = 返回空 list + log warning，**不**抛异常
- **TDD**:
  1. 给定一个真实 wiki 页面 → 返回 `Evidence` list（每条 source 一项）
  2. 给定不存在的 page_id → 返回空 list + warning
  3. 解析失败（frontmatter 损坏）→ 返回空 list，**不**让调用方崩溃
- **Acceptance**: 3 测试全过；commit `feat(evidence): query api`

---

### Task T-C3：最小 Protocol 接缝（仅 LLM + Parser）

> **为什么必做**：LLM Provider 已经有 `registry.py`，Parser 各自分散。**接缝是为后续 B 段 Plugin Manifest 铺路**，本阶段只做"协议化"，不引入新依赖。

#### T-C3.1 `Parser` Protocol + Registry

- **Files**:
  - `src/contracts/parser.py`（新文件，Protocol 类，3 方法）
  - `src/contracts/registry.py`（新文件，`ParserRegistry.discover(uri: str)` 路由函数）
  - `src/utils/extract/{pdf,docx,xlsx,md,txt,html}.py`（**包**成 `*Parser` 类，**不改**实现）
  - `src/pipeline/collector.py`（改一处 import：`if-elif` → `ParserRegistry.discover`）
  - `tests/test_contracts/test_parser_protocol.py`（新文件，6 测试）
- **Protocol 定义**:
  ```python
  class Parser(Protocol):
      name: str
      def can_parse(self, source: str | Path) -> bool: ...
      def parse(self, source: str | Path) -> str: ...
      def canonicalize(self, raw: str, metadata: dict) -> CanonicalDocument: ...
  ```
- **关键约束**:
  - **不**改 `collector.py` 的语义：HTML 在 URL 模式下走、在文件模式下抛
  - 各 `*Parser` 是 **thin wrapper**：原 `extract_*()` 函数保留，`PdfParser.parse()` 调 `extract_pdf()`
- **TDD**:
  1. `ParserRegistry.discover("foo.pdf")` → 返回 `PdfParser`
  2. 同上 docx/xlsx/md/txt
  3. `.html` 在 URL 模式返回 `HtmlParser`，在文件模式抛 `UnsupportedFileType`
  4. `ParserRegistry.list()` 返回所有已知 parser 的 name list
  5. `Collector.collect(source="foo.pdf")` 走 registry 后行为不变（用现有 collector 单测守住）
  6. 未知后缀 → 抛 `UnsupportedFileType("extension=.xyz")` 与原行为一致
- **Acceptance**: 6 测试全过；现有 collector 单测无回归；commit `feat(contracts): parser protocol + registry`

#### T-C3.2 `ProviderManifest` dataclass + healthcheck 函数

- **Files**:
  - `src/contracts/provider_manifest.py`（新文件）
  - `src/llm/registry.py`（**只**给 `ProviderConfig` 加 `manifest: ProviderManifest | None` 字段，默认 None）
  - `src/llm/healthcheck.py`（新文件，纯异步函数）
  - `tests/test_llm/test_provider_manifest.py`（新文件，5 测试）
- **Manifest dataclass**:
  ```python
  @dataclass
  class ProviderManifest:
      plugin_id: str                     # e.g. "openai-v1"
      plugin_version: str                # semver
      capabilities: list[str]            # e.g. ["chat", "embeddings"]
      contract_version: str              # "0.1"
      healthcheck_endpoint: str | None   # e.g. "/v1/models"
  ```
- **Healthcheck 函数**:
  ```python
  async def healthcheck(provider_name: str, config: ProviderConfig) -> dict:
      """返回 {ok: bool, latency_ms: int, reason: str | None}"""
  ```
- **不动**:
  - 各 `*_provider.py` 实现
  - `ProviderRegistry.load()` 的加载流程
  - 现有 `ProviderRegistry.get()` / `get_default()` 行为
- **TDD**:
  1. `ProviderManifest` 构造 + 字段读写
  2. `healthcheck("openai")` 网络失败 → `ok=False, latency_ms=0, reason="connection"`
  3. `healthcheck("openai")` 网络成功 → `ok=True, latency_ms>0`
  4. legacy `ProviderConfig` 无 manifest 字段时不抛错（兼容）
  5. `contract_version` 不匹配时 `healthcheck` 抛 `ContractMismatchError`
- **Acceptance**: 5 测试全过；现有 LLM 单测无回归；commit `feat(llm): provider manifest + healthcheck`
- **前提**：用 `httpx.AsyncClient` + `monkeypatch` mock 网络，否则 CI 跑 30s+

---

### Task T-C4：Policy Engine 最小可用版

> **为什么必做**：KC §28 要求判定集中化。当前判定散落在 `quality_gate.py` / `c_grade_handler.py` / `heat.py` / `audit_hard.py` 4 个文件。**本阶段只搬判定，不加新规则**。

#### T-C4.1 PolicyEngine dataclass + 入口函数

- **Files**:
  - `src/policy/engine.py`（新文件，`PolicyEngine` class + `PolicyDecision` dataclass）
  - `src/policy/rules/archive_rule.py`（新文件，单条规则函数）
  - `tests/test_policy/test_engine.py`（新文件，4 测试）
- **PolicyEngine 接口**:
  ```python
  class PolicyEngine:
      def __init__(self, rules: list[Rule] = None): ...
      def evaluate(self, context: dict) -> PolicyDecision: ...

  @dataclass
  class PolicyDecision:
      allowed: bool           # 是否放行
      severity: str           # "info" | "warn" | "block"
      reasons: list[str]      # 触发的规则名
  ```
- **规则 1: archive_rule**(搬运现有 `heat.py`):
  ```python
  def archive_rule(ctx: dict) -> PolicyDecision | None:
      """heat < 10 → archive"""
      heat = ctx.get("heat")
      if heat is not None and heat < 10:
          return PolicyDecision(allowed=False, severity="block", reasons=["heat_too_low"])
  ```
- **关键约束**:
  - **不**改 `heat.py` 的现有逻辑
  - **不**改 CLI / HTTP 行为
  - 现有 `heat_cmd` 与 `zombie.py` 仍走原代码路径
- **TDD**:
  1. `PolicyEngine([archive_rule]).evaluate({"heat": 5})` → `allowed=False, severity="block"`
  2. `evaluate({"heat": 50})` → `allowed=True`（无规则命中时默认）
  3. `evaluate({})` → `allowed=True`（无 heat 信息时不阻塞）
  4. `PolicyEngine([])` 空规则列表时 evaluate 不抛错
- **Acceptance**: 4 测试全过；commit `feat(policy): minimal engine + archive rule`

#### T-C4.2 PolicyEngine 接入 heat_cmd（仅 zombie 判定）

- **Files**:
  - `src/cli_ext/heat_cmd.py`（改一处：`zombie` 子命令的判定逻辑改用 `PolicyEngine`）
  - `tests/test_cli_ext/test_heat_cmd_policy.py`（新文件，2 测试）
- **约束**:
  - 现有 `python -m src.cli heat zombies` / `archive` 子命令**行为不变**
  - 仅替换判定调用：`run_hard_audit()` 之后追加 `policy.evaluate()`
  - policy 返回 `allowed=False` 时行为同 `run_hard_audit` 拒绝（**不能**双重拒绝造成不同行为）
- **TDD**:
  1. heat=5 + 现有 audit 拒绝 → 命令行为同改造前
  2. heat=50 + 现有 audit 通过 → 命令行为同改造前
- **Acceptance**: 2 测试全过；现有 heat_cmd 单测无回归；commit `refactor(heat): use policy engine`

---

## 阶段 A：纪律优先（再做这段）

> **核心动作**：规则定义清楚，写入文档，写入 pre-commit 钩子，**让后面写代码无法违反**。

### A 阶段总目标（验收）

- [ ] 命名/目录/契约/依赖 4 类规范已 DOC 化，并在 PR 评审时可被引用
- [ ]（可选）pre-commit 钩子防止违规
- [] 本阶段新增 5 个模块（`src/contracts/`, `src/evidence/`, `src/policy/`, `src/plugin_manager/`, etc.）都有 docstring + 简表

---

### Task T-A1：4 类规范定稿

#### T-A1.1 命名规范

- **Files**:
  - `docs/conventions/naming.md`（新文件）
- **必填内容**:
  - 模块名：单数复数规则 / 缩写列表 / 缩写大小写规则（`URL` 不 `Url`）
  - 文件名：snake_case 例外（已是现状，沿用）
  - 类名：PascalCase / 异常类以 `Error` 结尾
  - 函数名：动词开头 / 异步加 `async_` 命名规则（本项目**约定**）
  - 字段名：本项目**禁止**引入同义字段（如同时存在 `quote` 与 `text`）
  - 数据库列名：snake_case（沿用现状）
  - **每个规则一段示例代码 + 反例**
- **Acceptance**: 文件存在；CI 评审时新 PR 是否违反可被一眼看出；commit `docs(conventions): naming-spec`

#### T-A1.2 目录规范

- **Files**:
  - `docs/conventions/directory.md`（新文件）
- **必填内容**:
  - **新顶级目录** `< 3 个提案**必须**先 ADR，否则禁止新增**
  - 子目录布局：本项目现有约定（`core/storage/features` vs 旧的 `wiki/ensure.py`）
  - 测试目录：镜像 `src/` 一级，且每个测试包独立 `conftest.py`
  - 数据目录：`.index/` 下分类（vectors/cache/log/staging/quarantine/dedup_history）
  - 配置目录：`~/.config/ruflo-kb/` vs 项目内 `.llm-wiki/`
- **Acceptance**: 文件存在；新顶级目录需先 ADR 的规则可被检索；commit `docs(conventions): directory-spec`

#### T-A1.3 入参出参规范

- **Files**:
  - `docs/conventions/contract.md`（新文件）
- **必填内容**:
  - **入参规范**: dataclass 优先 / 禁止位置参数 > 5 个
  - **出参规范**: dataclass 优先 / tuple / dict 各自适用场景
  - **错误**: 业务异常本项目**约定**以 `*Error` 后缀 / 系统异常用原始
  - **可空性**: `Optional[T]` 显式标注 / 禁止 `T | None` 隐式
- **Acceptance**: 文件存在；commit `docs(conventions): contract-spec`

#### T-A1.4 依赖引入规范

- **Files**:
  - `docs/conventions/dependencies.md`（新文件）
- **必填内容**:
  - **stdlib 优先**: 能用 stdlib 不用第三方
  - **已有依赖优先**: 引入新依赖前 grep pyproject.toml
  - **许可证白名单**: MIT / BSD / Apache-2.0 / PSF（与 rufflo-kb 一致）
  - **依赖尺寸预算**: 单依赖 < 5MB 安装体积（wheel 视角）
  - **离线 wheel 路径**: 通过 `docs/environment/wheels/` 走，避免代理
  - **决策树**: 找不到 stdlib → 已装第三方 → 新依赖（**先 ADR**）
- **Acceptance**: 文件存在；commit `docs(conventions): dependencies-spec`

---

### Task T-A2：CI 守门（🟡 可选）

#### T-A2.1 ruff 引入

- **Files**:
  - `pyproject.toml`（加 `[tool.ruff]` section，与现有 `setuptools` 后端并列）
  - `ruff.toml`（新文件，per-project ignore 规则）
  - `.pre-commit-config.yaml`（新文件，照搬类似规则）
- **约束**:
  - **第一轮**只引入 `ruff check`（不引入 formatter），避免大范围重写
  - ignore 列表必须显式写在 `ruff.toml`
- **关键决策**:
  - **Q1**: 是否引入 ruff？**默认引入**，但**第一轮**只对**新写**文件生效（`exclude = ["src/legacy/**"]`）
  - 不破坏现有 1163 测试
- **Acceptance**: `ruff check src/contracts/ src/evidence/ src/policy/` 全过；commit `chore(ci): ruff select per-folder`

#### T-A2.2 pre-commit 钩子

- **Files**:
  - `.pre-commit-config.yaml`（新增段：4 规范 doc 引用 + ruff check）
  - `docs/conventions/pre-commit-setup.md`（开发者上手指南）
- **约束**:
  - 钩子**只**检查新增文件，存量代码不强制
  - **不**自动改代码（避免 commit 噪声）
- **Acceptance**: 本地 `pre-commit run --all-files` 在新写文件上有输出；存量无新增告警；commit `chore(ci): pre-commit-hooks`

---

### Task T-A3：Doc registry

#### T-A3.1 新增模块进 doc 注册表

- **Files**:
  - `docs/architecture/module-catalog.md`（新文件，照搬 `docs/architecture/` 已有目录结构）
  - 5 个新模块各加一节：`contracts/` / `evidence/` / `policy/` / `plugin_manager/` 预留目录
- **约束**:
  - 每个新模块必须有: 一句话描述 + 入口（文件名 + 行号）+ 公开 API list
- **Acceptance**: 文件存在；现有 `wiki/*` 模块可比照格式；commit `docs(architecture): module-catalog`

---

## 阶段 B：归一（最后做这段）

> **核心动作**：等 C 段"接缝"和 A 段"规矩"都稳定后，开始做大规模归一。本阶段产物：概念、API、数据存储路径都**只有一套**。

### B 阶段总目标（验收）

- [ ] Evidence 不再是"frontmatter 附属字段"——独立 dataclass + 独立持久化目录 + WikiPage 通过 `evidence_refs: list[str]` 引用
- [ ] `KnowledgeObject` 可以 `compute_diff()` 出结构化 Diff 并持久化到 `.index/diffs/`
- [ ] 旧知识被新知识替代时 `superseded_by` 字段 + `LifecycleState.SUPERSEDED` 同时建立
- [ ] `ProviderManifest` 升级为通用 `PluginManifest`，**新增 plugin_type 字段**

> ⚠️ **B 阶段每任务前必须做** `ponytail-review`：杀 over-engineering。**禁止**为"完备性"加新字段、新接口、新规则。

---

### Task T-B1：Evidence 一等公民 dataclass + 持久化目录

> **承接 C2.1**：C 段只做了 dataclass + query 函数；B 段做持久化。

#### T-B1.1 Evidence 持久化目录

- **Files**:
  - `.index/evidence/<evidence_id>.json`（新持久化目录）
  - `src/knowledge/evidence/storage.py`（新文件，read/write API）
  - `tests/test_knowledge/test_evidence_storage.py`（新文件，5 测试）
- **schema**:
  ```json
  {
    "evidence_id": "ev_<16hex>",
    "source_document_id": "doc_<id>",
    "source_block_id": "<n>",
    "quote": "<text>",
    "quote_hash": "<sha256-16hex>",
    "supports_claim_id": null,
    "confidence": 0.95,
    "created_at": 1734567890000
  }
  ```
- **约束**:
  - **不**改 `WikiPage.sources` 字段——保留作向后兼容回退
  - `WikiPage` **新增** `evidence_refs: list[str] = field(default_factory=list)` 字段
  - `.index/evidence/` 加入 `cache cleanup` 白名单（**不要**在 cache cleanup 中清理）
- **TDD**:
  1. `EvidenceStorage.write(evidence)` 写盘成功
  2. `EvidenceStorage.read("ev_xxx")` 返回对应 Evidence
  3. `EvidenceStorage.list_all()` 返回所有 evidence id
  4. 不存在的 evidence_id → 返回 None 而非抛错
  5. `WikiPage` 加 `evidence_refs` 后 round-trip 兼容旧页面（from_dict 默认空 list）
- **Acceptance**: 5 测试全过；现有 WikiPage 单测无回归；commit `feat(evidence): persistence + wiki ref`

#### T-B1.2 WikiPage reader 优先读 evidence_refs

- **Files**:
  - `src/wiki/storage/page_reader.py`（如果有；否则 `src/wiki/core/page_model.py`）—— 加一层：先查 `evidence_refs`，回退 `sources`
- **约束**:
  - **不**改 reader 返回值类型（保持向后兼容）
  - **不**动现有 Provenance dataclass
- **TDD**:
  1. WikiPage 同时含 `evidence_refs` 和 `sources` → reader 返回 `evidence_refs` 优先
  2. 仅含 `sources` → reader 返回从 sources 构造的弱 Evidence list
  3. 仅含 `evidence_refs` 且 references 找不到（磁盘丢了）→ warning + 回退到 sources
- **Acceptance**: 3 测试全过；commit `feat(wiki): reader prefers evidence_refs`

---

### Task T-B2：Knowledge Diff 工具

#### T-B2.1 Diff dataclass + 计算函数

- **Files**:
  - `src/knowledge/core/diff.py`（新文件，`KnowledgeDiff` dataclass + `compute_diff()` 函数）
  - `tests/test_knowledge/test_knowledge_diff.py`（新文件，5 测试）
- **KnowledgeDiff schema**:
  ```python
  @dataclass
  class KnowledgeDiff:
      added: list[str]           # KnowledgeObject.id
      changed: dict[str, list]   # id -> [{field, old, new}]
      removed: list[str]
      superseded: list[dict]     # [{old, new}]
      relation_changed: list[dict]
      evidence_changed: list[dict]
      confidence_changed: list[dict]
  ```
- **TDD**:
  1. 同一对象两版本 content 改 → `changed["knowledge_1"]` 含 Content.Changed
  2. 删除一个 relation → `relation_changed` 含 1 项
  3. confidence 0.7 → 0.9 → `confidence_changed` 含 1 项
  4. evidence_refs +1 → `evidence_changed` 含 1 项
  5. 旧版是 None（首次写入）→ 全空字段，不抛错
- **Acceptance**: 5 测试全过；commit `feat(knowledge): diff tool`

#### T-B2.2 Diff 写入 .index/diffs/

- **Files**:
  - `.index/diffs/<new_object_id>/<timestamp>.json`（新持久化目录）
  - `src/knowledge/core/diff_persistence.py`（新文件）
  - `src/knowledge/storage/event_store.py`（改一处：写入新版本时自动算 + 写盘）
  - `tests/test_knowledge/test_diff_persistence.py`（新文件，3 测试）
- **约束**:
  - **不**改 `KnowledgeObject.versions: list[VersionRef]` 数据结构
  - **不**改 event_store 的现有 emit 行为
- **TDD**:
  1. `event_store` 写入新对象 → 自动生成 diff 文件
  2. `compute_diff()` 失败 → 不阻塞 event_store（log warning）
  3. `.index/diffs/` 目录加入 `cache cleanup` 豁免清单
- **Acceptance**: 3 测试全过；commit `feat(knowledge): diff persistence`

#### T-B2.3 CLI `python -m src.cli diff`

- **Files**:
  - `src/cli_ext/diff_cmd.py`（新文件）
  - `src/cli.py`（加 `diff` 子命令）
  - `tests/test_cli_ext/test_diff_cmd.py`（新文件，3 测试）
- **约束**:
  - 命令语法：`python -m src.cli diff <page> [--to-version N] --project <id>`
  - **不**复刻 `git diff` 的 diff 格式——输出 JSON，避免误以为是 git diff
- **TDD**:
  1. 已知有 N 个 diff 文件的命令 → 打印 JSON 列表
  2. `--to-version N` → 只输出 ≤ N 版本
  3. page 不存在 → 报错并 exit 1
- **Acceptance**: 3 测试全过；commit `feat(cli): diff subcommand`

---

### Task T-B3：Superseded-by 关系 + LifecycleState 扩展

#### T-B3.1 `KnowledgeObject.superseded_by` 字段

- **Files**:
  - `src/knowledge/core/object.py`（加 `superseded_by: str | None = None`）
  - `tests/test_knowledge/test_supersedes_field.py`（新文件，4 测试）
- **不动**: 现有 `LifecycleState.DEPRECATED`
- **新增**: `LifecycleState.SUPERSEDED = "superseded"`
- **TDD**:
  1. `KnowledgeObject` 默认 `superseded_by = None`
  2. `set_superseded(old_obj, new_id)` 同时修改 old_obj 字段并写盘
  3. frontmatter round-trip 兼容旧页面无 `superseded_by`
  4. `LifecycleState` enum 含 9 项（8 现有 + SUPERSEDED）
- **Acceptance**: 4 测试全过；commit `feat(knowledge): supersedes field + state`

#### T-B3.2 Relation 注册 `SUPERSEDES`

- **Files**:
  - `src/wiki/features/relations.py`（注册新类型）
  - `tests/test_wiki/test_supersedes_relation.py`（新文件，3 测试）
- **TDD**:
  1. `RELATION_TYPES` 含 `"supersedes"`
  2. WikiPage relations list 查询 supersedes-backlinks 找到旧对象
  3. `python -m src.cli relations types` 输出含 `supersedes`
- **Acceptance**: 3 测试全过；commit `feat(relations): supersedes type`

#### T-B3.3 reconcile.py 接入 supersedes

- **Files**:
  - `src/pipeline/reconcile.py`（一处接入）
  - `tests/test_pipeline/test_reconcile_supersedes.py`（新文件，2 测试）
- **约束**:
  - 仅在 `reconcile_merge()` 已经检测到重复时调用
  - **不**改 merge 的现有判定逻辑
- **TDD**:
  1. 输入两个相同 entity → reconcile 时旧对象 `superseded_by = new_id`
  2. `LifecycleState` 同步改为 SUPERSEDED
- **Acceptance**: 2 测试全过；commit `feat(reconcile): use supersedes`

---

### Task T-B4（🟢 择机）：全量架构复审

> **承接 C3.2 的 `ProviderManifest`**：升级为通用 `PluginManifest`。

#### T-B4.1 ProviderManifest 升级为 PluginManifest

- **Files**:
  - `src/contracts/plugin_manifest.py`（新文件，**通用** Plugin Manifest）
  - `src/llm/registry.py`（保持 ProviderManifest 是 PluginManifest 的 LLM-specific 子集）
- **约束**:
  - `ProviderManifest` **不删**，作为 `PluginManifest` 的 alias
  - **不**引入 plugin 加载器（属于 Plugin Manager，C 级任务，先不做）
- **TDD**:
  1. `PluginManifest` 字段 ≥ `ProviderManifest`
  2. `PluginManifest` 增加 `plugin_type: str` 字段（"provider" | "parser" | ...）
  3. `ProviderManifest` 构造时 `plugin_type="provider"` 自动填充
- **Acceptance**: 3 测试全过；commit `feat(contracts): generic plugin manifest`

---

## 架构整改说明（防漂移清单）

### C 阶段不引入的（防过度工程）

| 不做 | 原因 |
|---|---|
| 不引入 `provider_factory` 之外的 LLM 抽象 | 当前 `ProviderRegistry` 够用 |
| 不改 `KnowledgeObject` 字段 | 现有 9 个字段 + 8 个 LifecycleState 不动 |
| 不引入新的 frontmatter 字段（除 Phase B 的 `evidence_refs`） | frontmatter 已够复杂 |
| 不引入 yaml/workflow loader | 与 ponytail 冲突 |
| 不引入 eval 数据集 | 没标注数据，指标无意义 |

### A 阶段不引入的

| 不做 | 原因 |
|---|---|
| 不引入 mypy（仅 ruff check） | 类型注解改造是另一项 PR |
| 不引入 formatter | 与现有格式不一致，会触发大范围 diff |
| 不引入 `setup.cfg` / `tox.ini` | 与 `pyproject.toml` 重复 |
| 不强制存量文件满足 ruff | 仅新写文件 + `exclude` 路径白名单 |

### B 阶段不引入的

| 不做 | 原因 |
|---|---|
| Faithfulness LLM-as-judge 默认开启 | 增加 LLM 调用 = 增加 token 成本 |
| 自动 Tag Proposal 流程 | 当前 `tags validate` 够用 |
| 入库评分 4 档（Core/Reference/Raw/Reject） | 与现有 `quality_settings.json` 双标准冲突 |
| Plugin Manager Lifecycle | C 级，明确不做 |
| Correction Pipeline | 没视频/音频接入需求 |

---

## 显式延后（不入本 plan，但有 ADR 留位）

| KC 章节 | 主题 | 触发条件 |
|---|---|---|
| §19 Tag Proposal 自动演化 | Tag 自动聚类/Promote | ≥ 100 个 Tag 时再启动 |
| §29 入库评分 4 档 | 评分机制重构 | `quality_settings.json` 被淘汰时 |
| §42 C 级整层 | Plugin Marketplace / SDK | 业务触发 |
| §43 A18 Evaluation | 8 指标固定测试集 | ≥ 100 条人工标注数据时 |

---

## 总体节奏

```
Day 1        Task T-C1.1, T-C1.2          ← 0.5 天
Day 1-3      Task T-C2.1, T-C2.2          ← 1.5 天
Day 3-6      Task T-C3.1, T-C3.2          ← 2 天
Day 6-8      Task T-C4.1, T-C4.2          ← 1.5 天
            ─── C 阶段完成 ───             代码可跑 + 5 个新模块存在
Day 9-13    Task T-A1.1 ~ T-A1.4          ← 4 天
Day 14      Task T-A2.1, T-A2.2           ← 1 天（可选）
Day 14      Task T-A3.1                   ← 0.5 天
            ─── A 阶段完成 ───             规矩 + 文档
Day 15+    Task T-B1.1 ~ T-B1.2          ← 1 周
Day 22+    Task T-B2.1 ~ T-B2.3          ← 1 周
Day 29+    Task T-B3.1 ~ T-B3.3          ← 1 周
Day 36+    Task T-B4.1（择机）             ← 1 天
            ─── B 阶段完成 ───             数据模型归一
```

**总工作量估计**：
- C 阶段：~6 天（🔴）
- A 阶段：~6 天（🔴 + 🟡）
- B 阶段：~3 周（🔴 + 🟡 + 🟢 择机）

---

## 测试策略（统一约束）

> 以下约束**所有任务通用**（不只是某 Task）。

### TDD 顺序
1. **先写测试** 看失败（red）
2. **再写实现** 让测试过（green）
3. **再 refactor** 不破坏测试（refactor）
4. **单 commit** + 见 `git workflow (auto-commit)` 节

### 测试命名
- `tests/test_<module>/test_<unit>.py`
- 与 `src/` 一级镜像
- 同名测试文件在 `test_X/` 不同目录下允许（pytest `--import-mode=importlib` 解决）

### 共享 fixture
- 已有 stub 模块（lancedb/pyarrow/pypdf）走现有 per-directory `conftest.py`
- 新加 mock（如 httpx）使用 `monkeypatch`，**不**全局 patch

### 验证命令
```bash
# 单文件
PYTHONPATH=. pytest tests/test_contracts/ -v

# 整段回归
PYTHONPATH=. pytest tests/test_knowledge/ tests/test_contracts/ \
  tests/test_policy/ tests/test_llm/ -v

# 全量（兜底）
PYTHONPATH=. python -m pytest --import-mode=importlib
```

---

## 防漂移约束（必须遵守）

⚠️ **Critical**：

1. 任务开始前**必须**回答 KC §46 的 10 个问题（特别是第 1 题："它是否直接服务于'碎片信息→可验证知识'？"）
2. ponytail ultra：如果某个任务"看起来需要"超过 **3 个新文件 + 2 个改文件**，停下来 review
3. 每任务 PR 只改 `Files` 列出的文件（**禁止**顺手"改进"周边代码）
4. 删字段/改 dataclass → 必须确认 back-compat test 守住（用 `.get(key, default)` 而非直接访问）
5. 任何 LLM 调用增加 → 必须有 OFF-by-default 开关（如 `RUFLO_FAITHFULNESS_ENABLED=false`）
6. 任何 commit 改动 `src/server/` / `src/cli.py` / `src/wiki/` 顶层 → 必须跑 `python -m src.cli serve --port <free>` + curl `/health` 验证 lifespan

---

## Definition of Done（每任务通用）

```
- [ ] 测试通过（单文件 + 全量无回归）
- [ ] .superpowers/sdd/progress.md ledger 更新
- [ ] 单个 commit（如预期需 follow-up commit 也允许）
- [ ] commit message 符合 `type(scope): 中文描述`
- [ ] 文档更新（若新增模块 → docs/architecture/module-catalog.md）
- [ ] 现有 1163 测试无回归
```

---

## Plan-audit 申报

> 本 plan 已经按 `.agents/skills/plan-audit/` 约束进行自查。审计将在 PR 评审前由独立子 agent 完成。两轮审计重点：

**Round 1（全面漏洞审计）**：
- C 阶段 `EvidenceAdapter.from_wiki_page()` 是否漏掉 source 为 URI 的情况？
- C3.2 `healthcheck` 在 CI 环境无网络时如何 fake？
- C4.2 接入 `heat_cmd` 时是否双重拒绝造成 diff 行为？

**Round 2（压力测试推演）**：
- B2.2 diff 写盘频率：每次 ingestion 都写吗？高频时磁盘 IO 影响
- B3.3 reconcile 调用链：如果 `reconcile_merge` 已有自己的 SUPERSEDED 判定，是否冲突？
- B4.1 Plugin Manifest 升级是否破坏现有 5 个 Provider 的 manifest load

---

## 关联参考（已存在）

- **同源规范**：`007 - 个人笔记/000 Inbox/2026-08-21 Knowledge Compiler.md`（非仓库）
- **历史借鉴**：
  - `docs/superpowers/plans/2026-08-19-llm-kb-design-absorption.md`（TDD-per-task + 整改说明格式）
  - `docs/superpowers/plans/2026-08-26-module-standardization-unification.md`（B 阶段模块归一思路）
- **测试基础设施**：`docs/environment/SETUP.md`（per-directory conftest）

---

## 第一个 commit 期望

> Task T-C1.1 / T-C1.2 是本 plan 的"零号 commit"。

```bash
git add docs/architecture/glossary-kc-mapping.md
git add docs/adr/2026-08-26-knowledge-compiler-absorption.md
git commit -m "docs(architecture): kc absorption glossary + ADR"
```

预期仓库在收到此 commit 后：
- `docs/architecture/glossary-kc-mapping.md` 存在
- `docs/adr/2026-08-26-knowledge-compiler-absorption.md` 存在
- 现有 1163 测试全部通过
- 无新增代码（这两个文件**仅**文档）
