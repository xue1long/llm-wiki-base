# Plan: 从 LLM_Knowledge_base_v2 吸收 wiki 设计(短内容分桶 + workflow_state)

- **status**: in_progress — 阶段 1 落地完成,阶段 2 (short-form 集成) plan-audit 三轮后整改到位,等待人工复核 + 开工
- **branch**: feature/2026-08-19-llm-kb-absorption
- **关联 ADR**:`docs/adr/2026-08-19-llm-kb-design-absorption.md`
- **参考 plan**:`docs/superpowers/plans/2026-08-19-capture-template-and-quick-entry.md`(capture 6 轮审查,部分字段/服务层模式参考)

## Goal

吸收 LLM_KB 两个对 ruflo-kb 有**结构性必要**的设计(不是工程优化):

1. **C 级碎片 short-form 兜底路径** —— 解决 LLM 处理短内容的结构性失败(扩写注水)
2. **`workflow_state` 状态机 + `verified_at` 字段** —— 解决 Agent 引用链缺人工 trust 边界

不吸收:命名空间标签(冲突)、sentinel 解析(冗余)、模板锁死(哲学冲突)、`compare_candidates`(等价已有)。

### 非目标(明确划界)

- 不改 Generator 协议(body slot → sentinel 不做)
- 不动 `tag_namespace.py`(已有 12 个 prefix 不动)
- 不改 `ReviewerStage` 的 4 个 rule 检查
- 不引入 `use_context` 字段(留待后续 ADR 评估)
- 不动 capture 模板(2026-08-19-capture plan 已收口)
- 不修改 `PageType` enum(short-form 是 processing_depth,不是 PageType)
- 不动 `render_body` 接口(在调用层做切换)

### 阶段性目标

- **阶段 1(已完成)**:`workflow_state` 状态机全模板生效;`detect_short_form` 函数实现并测试
- **阶段 2(本次待办)**:short-form 接入 Generator,防止 LLM 扩写短内容(整改后版本)

## 已确认决策(含 plan-audit 整改)

| # | 决策点 | 结论 |
|---|---|---|
| Q1 | 短内容判定阈值 | 中文字符数 < 200 **或** 步骤数 < 3 → memory |
| Q1a | 模板级阈值覆盖 | `template.json` 新增可选字段 `short_form_thresholds:{ chars, steps }` |
| Q2 | 短内容走哪个模板 | `processing_depth=memory` 触发,Generator 走 `short-form.md`(新模板) |
| Q3 | `processing_depth` 默认值 | `concept`(兼容存量) |
| Q3a | `processing_depth` 枚举校验 | `from_dict` 中加校验,非法值回退 `concept` |
| Q4 | `workflow_state` 默认值 | `draft`(兼容存量) |
| Q5 | `verified_at` 类型 | `int`(Unix ms) |
| Q6 | `workflow_state` 合法值 | `draft / ready / verified / outdated` |
| Q7 | 状态机自动流转 | `draft → ready` 由 `ReviewerStage` VALIDATED;`ready → verified` 由 `resolve_review`;`verified → outdated` 人工 |
| Q8 | 存量兼容 | 未设 `workflow_state` 的旧卡 → 视为 `draft` |
| Q8a | `workflow_state` 白名单校验 | `lint.py` 加白名单,非法值报错 |
| Q9 | 测试策略 | TDD:先写 round-trip + 决策树 + 状态机测试,再实现 |
| Q10 | 回滚策略 | 字段加 DEFAULT 兼容值,删除字段即可回滚 |
| Q11 | capture mark-verify | `capture` 写入的卡可通过 `mark-verify` 变 `verified`,绕过 `ReviewerStage` |
| Q12 | `_count_chinese_chars` Unicode 范围 | `[\u4e00-\u9fff\u3400-\u4dbf]` |
| Q13 | `_count_steps` 阿拉伯数字 | `第\d+[步点节]` |
| Q14 | `draft` 包含待审核 | 设计选择,文档说明 |
| Q15 | `detect_short_form()` 超时保护 | Unix `signal.alarm` + Windows `threading.Timer`,超时回退 `concept` |
| Q16 | `short-form.md` 路由失败 fallback | Generator 检测 memory 时若模板缺失,fallback 用 concept 模板 + warning log |
| Q17 | `mark-verify` 权限控制 | API `require_admin`(存在则用,缺失则 fallback no-op) |
| Q18 | lint 空字符串处理 | 空字符串视为 draft/concept,不报错 |
| Q22 | 短模板文件位置 | **仅** `src/wiki/templates/bundled/short-form.md`(单副本;取消双副本) |
| Q23 | short-form.md header | `<!-- wiki-template-type: concept -->`(通过 parser 校验;形态字段在 filename 而非 header) |
| Q24 | memory body 渲染 | LLM prompt 引导 + 末尾覆盖 `processing_depth` 字段;body 渲染按 page_type 走(`memory` 概念也用 CONCEPT 类型,但加载 short-form.md) |
| Q25 | source page 判定 | **`page_type == PageType.SOURCE`**,不比对 page.id 和 source_slug |
| Q26 | detect_short_form 集成点 | `generate_ingest` **入口**(LLM 调用前),计算 `processing_depth_hint` 传入 generator;**末尾不再强制覆盖**(避免与 LLM 选择冲突) |
| Q27 | prompt 注入位置 | **3 个 prompt 模板**,不是 4 处 base_prompt: `GENERATOR_PROMPT`(line 198)、`UNIFIED_PROMPT`(line 388)、`CANDIDATE_RENDER_PROMPT`(line 800);注入 `{SHORT_FORM_TEMPLATE}` 占位符 |
| Q28 | LLM slot 名一致性 | 不强制;LLM 选 summary/key_points/references 或 definition/characteristics 都接受,render_body 缺失 slot 自动用占位符 |
| Q29 | 模板加载 | 取消 _render_short_form_template_section 中遍历 `short-form.md` 多副本;只读 `src/wiki/templates/bundled/short-form.md` |
| Q30 | schema enum 限制 | **不修改**;LLM 仍可选 concept/memory/operation;prompt 引导 + 末尾 hint 注入 |

## 架构整改说明(plan-audit 后)

### 旧方案的问题(已废弃)

1. **Task 5.4 用 `page.id == source_slug`**: 永远不相等 → 覆盖逻辑失效
2. **Task 5.5 用 `render_body(page_type=CONCEPT, template_body=short-form)` 配 `wiki-template-type: short-form` header**: parser 抛 `TemplateParseError`
3. **R-T5-2 声称 schema enum 强制 memory**: 事实错误,enum 只能限制不能强制
4. **Plan 引用 "4 处 prompt 注入"**: 实际是 3 个 prompt 模板(GENERATOR/UNIFIED/CANDIDATE_RENDER)
5. **双模板副本(老 + 新)**: 老副本对 ingest 流程无用,纯结构噪声
6. **末尾强制覆盖**: 时机过晚,body 已按 LLM 选择渲染,字段不一致

### 新方案的关键变更

| 旧 | 新 | 理由 |
|---|---|---|
| `page.id == source_slug` | `page_type == PageType.SOURCE` | PageType 是结构化判定,稳定可靠 |
| 末尾强制覆盖 field | 入口计算 hint 传入 generator | 早期介入,LLM 看到 hint 后倾向选 memory;body 渲染时按 hint 选模板 |
| `render_body(page_type=CONCEPT, body=short-form-with-memory-header)` | short-form.md 用 `wiki-template-type: concept` header,page_type=CONCEPT 渲染 | parser 通过校验;物理层仍是 CONCEPT 类型 |
| 双副本(老 + 新) | 只新系统副本 | 老副本对 ingest 无用 |
| 4 处 prompt 注入 | 3 个 prompt 模板 + `{SHORT_FORM_TEMPLATE}` 占位符 | 精确位置,实施者按 template name 找 |

## Tasks

### Task 1: `WikiPage` 加 `workflow_state` + `verified_at` 字段 ✅ 已完成

- **Files**:
  - `src/wiki/core/types.py`(dataclass 加 2 字段 + `to_frontmatter_dict/from_dict` 同步)
  - `tests/test_wiki/test_workflow_state_roundtrip.py`(新文件,8 测试)
- **Acceptance**: 8 测试全过;1163 存量测试无回归;commit `40b091f2` 已推送

### Task 2: 短内容分桶决策函数 `detect_short_form()` ✅ 已完成

- **Files**:
  - `src/pipeline/short_form.py`(新模块,纯函数,跨平台超时保护)
  - `tests/test_pipeline/test_short_form.py`(新文件,14 测试)
- **Implementation**: 双平台超时(Windows `threading.Timer`,Unix `signal.alarm`),超时回退 concept
- **Acceptance**: 14 测试全过;commit `6b0bd19f` 已推送

### Task 3: `workflow_state` 与 capture mark-verify ✅ 已完成

- **Files**:
  - `src/services/capture.py`(`mark_page_verified()` + `mark_page_verified_rollback()` + `mark_page_verified_by_id()` + `PageNotFoundError`)
  - `src/wiki/features/lint.py`(workflow_state + processing_depth 白名单 + verified_at 一致性校验)
  - `tests/test_services/test_workflow.py`(10 测试)
  - `tests/test_wiki/test_lint_workflow_state.py`(5 测试)
- **Acceptance**: 15 测试全过;commit `15506f37` 已推送

### Task 4: capture mark-verify API + CLI ✅ 已完成

- **Files**:
  - `src/server/routes/capture.py`(`POST /verify` API + `require_admin` fallback)
  - `src/cli_ext/capture_cmd.py` + `src/cli.py`(`capture-mark-verify` CLI)
  - `tests/test_server/test_capture_verify.py`(2 测试)
- **Acceptance**: 2 测试全过;R10 边界守住;commit `fce27662` 已推送

### Task 5: short-form 接入 Generator(整改后版本) ⏳ 本次待办

#### 5.1 创建 `short-form.md` 模板(单副本)

- **Files**:
  - `src/wiki/templates/bundled/short-form.md`(新系统,被 Generator 实际调用)
- **模板内容**(精简 3 段,适配"短内容"形态,**header 用 concept 类型以通过 parser 校验**):
  ```markdown
  <!-- wiki-template-version: 2.0.0 -->
  <!-- wiki-template-type: concept -->

  ## 摘要

  <!-- slot:summary -->

  ## 核心观点

  <!-- slot:key_points -->

  ## 引用与来源

  <!-- slot:references -->
  ```
- **关键决策**(Q23): header 用 `concept` 类型,因为 short-form 是 processing_depth(逻辑维度),不是 PageType(物理维度);模板与 concept 类型共用 `render_body(page_type=CONCEPT)` 路径
- **取消**:`src/templates/bundled/general/.wiki-templates/short-form.md`(老系统对 ingest 流程无用)
- **Acceptance**: 文件存在;`render_body(template_body, slots, page_type=CONCEPT)` 不抛错

#### 5.2 Generator 添加 `_render_short_form_template_section()` 函数

- **Files**:
  - `src/pipeline/generator.py`(照搬 `_render_operation_template_section`,改路径为 `short-form.md`)
- **实现**:
  ```python
  def _render_short_form_template_section(project_root: Path) -> str:
      """Load the short-form template for prompt injection (memory-depth pages).

      Mirrors _render_operation_template_section: short-form is a processing_depth,
      not a PageType. The template is loaded as-is and injected into the prompt
      so the LLM knows which slots to use when processing_depth=memory.
      """
      from ..wiki.templates.types import BUNDLED_DIR, USER_TEMPLATE_DIR

      candidates = [
          project_root / ".wiki-templates" / "short-form.md",
          USER_TEMPLATE_DIR / "short-form.md",
          BUNDLED_DIR / "short-form.md",
      ]
      for path in candidates:
          try:
              if path.is_file():
                  return "### short-form\n" + path.read_text(encoding="utf-8").strip()
          except OSError as exc:
              _logger.warning("Could not load short-form template %s: %s", path, exc)
      return "(no short-form template available)"
  ```
- **Acceptance**: 函数签名与 `_render_operation_template_section` 对称

#### 5.3 Generator 3 个 prompt 模板注入 `{SHORT_FORM_TEMPLATE}` 段

- **Files**:
  - `src/pipeline/generator.py`
- **修改 1**: `GENERATOR_PROMPT` (line 198-378, 在 `{OPERATION_TEMPLATE}` 后追加):
  ```python
  ## Short-form template (used when processing_depth=memory)
  {SHORT_FORM_TEMPLATE}
  ```
- **修改 2**: `UNIFIED_PROMPT` (line 388-?, 在 `{OPERATION_TEMPLATE}` 后追加): 同上
- **修改 3**: `CANDIDATE_RENDER_PROMPT` (line 800-?, 在 `{OPERATION_TEMPLATE}` 后追加): 同上
- **修改 4**: 4 个 base_prompt `.format()` 调用 (line 646/1028/1254/1499) 加 `SHORT_FORM_TEMPLATE=_render_short_form_template_section(paths.root),`
- **Acceptance**: 3 个 prompt 模板都有 `{SHORT_FORM_TEMPLATE}` 占位符;4 处 base_prompt 都有对应参数;grep 验证

#### 5.4 Generator 添加 `processing_depth_hint` 参数(Q26)

- **Files**:
  - `src/pipeline/generator.py`
- **改动**: 在 4 个 `generate_*` 函数 (`unified_generate`、`generate_from_candidate`、`generate_from_knowledge_object`、`generate`) 的签名中加:
  ```python
  processing_depth_hint: Optional[str] = None,  # "memory" | None
  ```
- **改动 2**: 在 body 渲染决策处 (line 1336-1344 区域,各函数都有类似逻辑):
  ```python
  template = resolved_templates.get(page_type)
  if template is None:
      body_md = ""
  elif processing_depth_hint == "memory" and page_type == PageType.CONCEPT:
      # Use short-form template (memory-depth concept page)
      try:
          short_form_body = _load_short_form_template(paths.root)
          body_md = render_body(
              template_body=short_form_body,
              slots=p.get("slots", {}) or {},
              page_type=page_type,  # CONCEPT — 通过 parser 校验
              template_version=template.version or "",
          )
      except FileNotFoundError:
          _logger.warning("short-form.md missing, falling back to concept template")
          body_md = render_body(...)  # 原 logic
  else:
      body_md = render_body(...)  # 原 logic
  ```
- **改动 3**: 新增 `_load_short_form_template(project_root)` 辅助函数,照搬 `_render_short_form_template_section` 的 candidates 列表但返回 template body 而非 prompt section
- **Acceptance**: hint="memory" + page_type=CONCEPT → 用 short-form.md;hint=None 或其他 → 用原模板;FileNotFoundError fallback

#### 5.5 `generate_ingest` 入口计算 `processing_depth_hint`(Q26)

- **Files**:
  - `src/pipeline/ingest.py`
- **改动**: 在 `generate_ingest` 入口(line 491 附近),LLM 调用前:
  ```python
  from .short_form import detect_short_form

  # Compute processing_depth hint based on source content
  # This is a HINT, not a forced override — LLM can still choose otherwise
  _decision = detect_short_form(_sanitized_source_text)
  _processing_depth_hint = _decision.processing_depth  # "memory" or "concept"
  _logger.debug(
      "[generate_ingest] processing_depth_hint=%s chars=%d steps=%d timed_out=%s",
      _processing_depth_hint, _decision.char_count, _decision.step_count, _decision.timed_out,
  )
  ```
- **改动 2**: 传递 hint 给 `_generate`/`unified_generate`/`generate_from_knowledge_object`/`generate_from_candidate` 调用(line 624、654、695、1049 附近):
  ```python
  pages = await _generate(
      ...,
      processing_depth_hint=_processing_depth_hint,
  )
  ```
- **改动 3**: `_generate(**kwargs)` 透传 `processing_depth_hint`(line 381-383)
- **Acceptance**: hint 通过 kwargs 链传到 4 个 generate_* 函数;短内容触发时 hint="memory"

#### 5.6 集成测试

- **Files**:
  - `tests/test_pipeline/test_short_form_integration.py`(新文件,6 测试)
- **Test**:
  1. `test_short_form_template_loadable` — `src/wiki/templates/bundled/short-form.md` 存在且 header 格式正确
  2. `test_render_short_form_template_section_returns_template` — 函数返回包含 `### short-form` 段
  3. `test_load_short_form_template_returns_body` — `_load_short_form_template` 返回模板 body 字符串
  4. `test_short_form_renders_with_concept_page_type` — `render_body(template_body=short-form, page_type=CONCEPT)` 不抛错(Q23 关键)
  5. `test_generate_unified_uses_short_form_on_memory_hint` — 单元测试 mock: 调用 `unified_generate(processing_depth_hint="memory")`,断言内部加载 short-form.md
  6. `test_generate_falls_back_to_concept_on_missing_template` — 删除 short-form.md, hint="memory" 不报错,fallback 用 concept
- **Acceptance**: 6 测试全过;不修改现有 7 个模板的 round-trip

#### 5.7 全量回归

- 跑 `tests/test_wiki/`, `tests/test_pipeline/`, `tests/test_services/`, `tests/test_server/`, `tests/test_cli_ext/`
- 预期: 不新增失败(3 个预存 mojibake + pipeline 测试失败除外)
- 重点验证:
  - 7 个 bundled 模板的 `.wiki-templates/*.md` 不受影响
  - capture 流程(services/capture.py)不受影响
  - 4 个 generate_* 函数对 hint=None 的行为不变
  - LLM stub 测试不会被新 prompt 段打断

#### 5.8 commit

- 一个 commit:`feat(pipeline): short-form 路由接入 Generator(prompt + body fallback + processing_depth_hint)`
- 按 AGENTS.md "Git workflow" 规则,中文 commit 信息

### Task 6: ADR 状态升级 + 文档同步

- **Files**:
  - `docs/adr/2026-08-19-llm-kb-design-absorption.md`(状态: Proposed → Accepted)
  - `docs/adr/INDEX.md`(同步状态)
  - `.superpowers/sdd/progress.md`(更新进度 ledger)
  - `.memory/feedback-llm-kb-absorption.md`(经验沉淀)
- **Acceptance**: ADR 状态反映实施完成

## Audit 追踪

### 前 4 轮(workflow_state + detect_short_form 阶段)
- Round 1: ✅ 2 致命 + 3 重大 + 5 优化
- Round 2: ✅ 3 重大 + 9 优化
- Round 3: ✅ 2 致命 + 2 重大 + 4 优化
- Round 4: ✅ 2 致命 + 4 重大 + 2 优化

### 第 5 轮(short-form 集成方案): ✅ 已整改
**原发现**:
- ①致命缺陷 3 项(F-T5-1 page.id 永不等于 source_slug / F-T5-2 render_body parser 抛错 / F-T5-3 schema enum 不能强制)
- ②重大隐患 5 项(H-T5-1 ~ H-T5-5: 行号错误、source_slug 不可访问、覆盖时机错位、LLM slot 名不一致、无通信通道)
- ③优化疏漏 6 项(M-T5-1 ~ M-T5-6)

**整改映射**:
| 原始问题 | 整改方案 |
|---|---|
| F-T5-1 page.id 不等于 source_slug | Q25: 改用 `page_type == PageType.SOURCE` 判定;Task 5.4 改为入口 hint 计算,不依赖 page.id |
| F-T5-2 parser 抛错 | Q23: short-form.md header 改用 `wiki-template-type: concept`,`page_type=CONCEPT` 渲染通过校验 |
| F-T5-3 schema enum 不能强制 | Q26 + Q30: 取消强制;改用 hint + prompt 引导 + LLM 自主选择 |
| H-T5-1 行号错误 | Q27: 明确 3 个 prompt 模板名 + 精确行号 |
| H-T5-2 source_slug 不可访问 | Q25: 入口用 source_text 算 hint,不依赖 source_slug 变量 |
| H-T5-3 覆盖时机错位 | Q26: 入口计算 hint 提前到 LLM 调用前 |
| H-T5-4 LLM slot 名不一致 | Q28: 不强制;render_body 缺失 slot 用占位符(已存在行为) |
| H-T5-5 无通信通道 | Q26: 新增 `processing_depth_hint` 参数链 |
| M-T5-1 LLM 看到 prompt 段被误导 | 通过 Q27 显式说明模板用途;Q28 不强制 |
| M-T5-2 双副本理由不成立 | Q22: 取消双副本,只新系统单副本 |
| M-T5-3 quality_gate 时序 | hint 在入口,quality_gate 在中间,顺序正确 |
| M-T5-4 extra_pages 不覆盖 | Task 5.4 不再覆盖,改 hint;LLM 决策对所有 pages 一致 |
| M-T5-5 `_generate` 实际调用 | Task 5.4 已列 4 个 generate_* 都需改 |
| M-T5-6 重 ingest 兼容性 | hint 是 deterministic 重新计算,幂等 |

### 第 5 轮整改后新增风险

| # | 风险 | 加固 |
|---|---|---|
| **R-T5R-1** | LLM 忽略 hint 仍选 concept | body 渲染按 hint 强制 short-form 模板(5.4);即使 LLM 选 concept slot 名,render_body 仍用 short-form 模板(只用 summary/key_points/references),其他 slot 缺失用占位符 |
| **R-T5R-2** | `_load_short_form_template` 与 `_render_short_form_template_section` 重复逻辑 | 两函数都读同一路径,但一个返回 body 一个返回 prompt section;DRY 可后续抽公共函数 |
| **R-T5R-3** | short-form 模板的 3 个 slot 名与 concept 模板 5 个 slot 名不一致 | render_body 处理:缺失 slot 用占位符;LLM 即使填了 concept slot 名,在 short-form 模板下也只用到 summary/key_points/references |
| **R-T5R-4** | `processing_depth_hint` 透传到 4 个 generate_* 函数,某个遗漏 | 测试覆盖 + grep 验证 4 处都有 hint 参数 |
| **R-T5R-5** | 长内容 + 短步骤矛盾(`chars=1000, steps=1` → memory) | 接受设计选择:`OR` 逻辑优先 steps 少;用户可用 `template_thresholds` 覆盖 |

### Rollback

- Task 5.1 模板文件可删除
- Task 5.2 函数可删除
- Task 5.3 prompt 注入可回退(删除 3 处 `{SHORT_FORM_TEMPLATE}` 占位符 + 4 处 base_prompt 参数)
- Task 5.4 `processing_depth_hint` 参数可删除(签名恢复 + body 渲染逻辑恢复)
- Task 5.5 入口 hint 计算可删除
- 退化到当前状态: short-form 函数已实现但未接线
- 存量 wiki 不受影响(processing_depth 字段默认 concept)

## Completion evidence(待填)

- Final commit: pending (Task 5)
- Tests: pending (Task 5.6 加 6 测试,合计 45 个新测试)
- Documentation updated: pending (Task 6)
- Progress ledger updated: pending
