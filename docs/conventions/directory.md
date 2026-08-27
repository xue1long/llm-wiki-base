# 目录布局规范（Directory Layout）

> 适用范围：`src/`、`tests/`、`scripts/`、项目级配置目录、运行时数据目录。
>
> 本规范**吸收** plan v1 中 "目录约定" 的精神，但以**正式文档**形式定稿，
> 后续所有新模块/新测试目录都按本文档放置。

## 1. 顶级目录变更门控

- **任何新顶级目录（`src/<new_pkg>/`、`scripts/<new_dir>/`、`tests/test_<new_pkg>/`、
  `docs/<new_section>/`）必须先写 ADR**，例外仅限以下三类：
  1. 一次性临时目录（如 `docs/migration/legacy-snapshot-2026-08-26/`）。
  2. 已在路线 v2.2 中立项的目录（`src/kc/`、`src/kc/contracts/` 等）。
  3. 用户在主对话中**显式指令**的目录。
- **提案 ≥ 3 个未 ADR 的新顶级目录 → 拒绝该 commit**（A-5 验收硬指标）。
- ADR 模板见 `docs/adr/_template.md`，决策须含 §Context / §Decision / §Rationale / §Consequences。

```text
✅ 新顶级目录前：先提交 docs/adr/2026-MM-DD-<topic>.md
❌ 直接 mkdir src/<new_pkg>/ 并写代码（违反本规范）
```

## 2. `src/` 子目录布局

- **沿用现状**：`src/wiki/core/` / `src/wiki/storage/` / `src/wiki/features/` 三层切分。
  - `core/`：纯数据模型 + 类型（dataclass / enum），不依赖 IO。
  - `storage/`：文件系统 / 数据库读写（`WikiPaths`、`ensure.py`、`lancedb` 适配）。
  - `features/`：业务能力（`relations.py`、`folder_ingest.py`、`heatmap.py`）。
- **新业务包**沿用三层（`core` / `storage` / `features`），禁止扁平化（`src/wiki/ensure.py` 旧路径已废弃——见 AGENTS.md）。
- **`src/kc/`（Knowledge Compiler 路线 v2.1+）**子目录：
  - `domain/`：领域模型（KO / KU / 实体 dataclass）。
  - `contracts/`：跨层接口契约（详见 `contract.md`）。
  - `adapters/`：与外部（WikiPage / LanceDB / HTTP）的适配器。
  - `evidence/`、retrieval/`、`compiler/`、`backup/`：按职责分子包。
- **`src/services/`**：业务逻辑层（HTTP 路由 ↔ core/domain 之间）。
- **`src/server/`**：FastAPI 路由（**薄适配器**）。
- **`src/cli.py`** + **`src/cli_ext/`**：CLI 入口与子命令扩展。
- **`src/lib/`**：跨包公共 helper（`project.py`、`write_hooks.py` 等）。

```text
src/
├── wiki/
│   ├── core/         # WikiPage / PageType / Relation（无 IO）
│   ├── storage/      # WikiPaths / ensure / lancedb 适配
│   ├── features/     # relations / folder_ingest / heatmap
│   └── templates/    # 前置 prompt 模板
├── kc/               # 路线 v2.1+ 新增（已 ADR）
│   ├── domain/
│   ├── contracts/
│   ├── adapters/
│   ├── evidence/
│   ├── retrieval/
│   ├── compiler/
│   └── backup/
├── services/         # 业务逻辑层（files / projects / ingest / search / chat / quality / ...）
├── server/           # FastAPI 路由（薄适配器）
├── pipeline/         # Collector / Analyzer / Generator
├── orchestrator/     # 多 agent 调度
├── llm/              # LLM provider 注册表
├── vector/           # LanceDB 单例
├── schemas/          # 迁移框架
├── queue/            # 异步任务队列
├── events/           # EventBus + payload
├── metrics/          # 16 项指标计算
├── maintenance/      # 周期清理任务
├── knowledge/        # 知识图谱
├── research/         # 检索 / 浏览
├── vision/           # 图像提取
├── utils/            # 通用工具（idempotency / extract）
├── lib/              # 跨包 helper
├── permissions.py    # 权限
├── circuit_breaker.py # 熔断器
├── types.py          # 全局类型
├── config.py         # 配置加载
└── cli.py            # CLI 入口
```

## 3. `tests/` 目录镜像

- **镜像 `src/` 一级**（`AGENTS.md` 既有约定）：
  - `tests/test_<module>.py` 对应顶层模块（`tests/test_permissions.py`）。
  - `tests/test_<package>/test_<file>.py` 对应子包（`tests/test_wiki/test_paths.py`）。
- **每个测试包独立 `conftest.py`**：负责本地 stub heavy deps（lancedb / pyarrow /
  mcp / tavily 等），并按需 `sys.modules.setdefault` 模式（详见
  `docs/environment/SETUP.md` §4 兄弟 conftest 级联风险）。
- **辅助目录**：
  - `tests/support/`：跨包共享 fixture（不参与镜像）。
  - `tests/test_integration/`：跨包 e2e（不镜像单一模块）。
  - `tests/__init__.py`：允许为空（保证 `pytest --import-mode=importlib` 行为）。

```text
tests/
├── conftest.py              # 全局 fixture（轻量；不装 heavy stub）
├── test_<module>.py         # 顶层模块直接对应
├── test_<package>/          # 子包镜像
│   ├── conftest.py          # 本包 heavy-stub
│   └── test_<file>.py
├── support/                 # 跨包共享
└── test_integration/        # e2e / 跨包集成
```

## 4. 数据目录 `.index/`（按分类）

- **位置**：项目根 `<project>/.index/`（沿用 `python -m src.cli project init` 现行布局）。
- **分类与职责**（每类一个子目录，**禁止混用**）：

| 子目录 | 性质 | 内容 | 清理策略 |
|---|---|---|---|
| `.index/lancedb/` | 生产数据 | 1536 维向量 embeddings | **不可清**（生产数据；走 schema 迁移） |
| `.index/lint_cache/` | cache | LLM lint 结果（TTL 24h） | 安全清（`cache cleanup`） |
| `.index/heat_events.log` | log | heat 变更审计流 | 安全清（按日志滚动） |
| `.index/reviews.json` | config | 待评审项 | 安全清（归档到 `reviews_resolved.json`） |
| `.index/reviews_resolved.json` | log | 已决议的评审历史 | 仅追加；可归档 |
| `.index/staging/` | temp | zombie 页面草稿 | 安全清（已 commit 后） |
| `.index/quarantine/` | temp | 被 REJECTED 的页面 + 拒绝理由 | 安全清（人工决策后） |
| `.index/dedup_history/` | temp | merge 实体归档 | 安全清（人工审计后） |
| `.index/quality_settings.json` | config | 质量门阈值 | **不可清**（人工配置） |
| `.index/batch_build_state.json` | config | 批量 ingest 进度 | 安全清（任务结束后） |
| `.index/shadow/`（仅 `RUFLO_SHADOW_MODE=true`） | log | legacy vs candidate 对比报告 | 安全清 |

```text
✅ 单一职责：每类（生产/cache/log/temp/config）独占子目录
❌ 把 lint_cache 放在 .index/heatmap/、把 staging 放在 .index/lancedb/
```

## 5. 配置目录

- **用户全局配置**：`~/.config/ruflo-kb/`（沿用 XDG Base Directory 规范）：
  - `llm-providers.json`（provider 注册表加载位置，见 AGENTS.md）。
  - 其他跨项目配置（待规划）。
- **项目内配置**：`<project>/.llm-wiki/`（**项目元数据，非 cache**）：
  - `project.json`（UUID / 名称 / schema 版本）。
  - `slug_aliases.json`（CJK slug → canonical alias 注册表）。
  - `.backup/`（schema 迁移安全备份）。
- **不要混用**：用户全局与项目内配置**目录分离**；不要把 `project.json` 写到
  `~/.config/ruflo-kb/`。

```text
✅ 项目元数据：<project>/.llm-wiki/project.json
✅ 用户 provider：~/.config/ruflo-kb/llm-providers.json
❌ 把 project.json 写到 ~/.config/ruflo-kb/<project_id>/project.json
```

## 6. 脚本目录 `scripts/`

- **顶层命名**：`kc_<purpose>.py` / `phase<N>_<purpose>.py` / `audit_<topic>.py` 等 snake_case。
- **新脚本无需先 ADR**，但若引入**新依赖**则按 `dependencies.md` §决策树 处理。
- **CI/验收脚本**（`kc_check_delivery_report.py` 等）放置在 `scripts/`，并在
  `tests/test_scripts/` 镜像测试（若脚本有可测部分）。

## 7. 文档目录 `docs/`

- **`docs/architecture/`**：架构契约与子规范（如 `frontmatter-schema-policy.md`、
  `naming.md` KC 词汇）。
- **`docs/conventions/`**（本目录）：命名 / 目录 / 契约 / 依赖 4 类代码规范 + ADR 模板。
- **`docs/adr/`**：所有重大架构决策记录（使用 `docs/adr/_template.md`）。
- **`docs/guides/`**：用户/开发者操作手册（如 `wiki-spec.md`）。
- **`docs/environment/`**：环境与构建说明（`SETUP.md`、`requirements-*.txt`、
  `wheels/` 用于离线 wheel 路径——见 `dependencies.md`）。
- **`docs/superpowers/plans/`**：路线与计划文档（plan-audit 两轮自审后落地）。
- **`docs/agents/`**：AI agent 操作守则（`issue-tracker.md` / `domain.md`）。
- **`docs/audits/`、`docs/evaluations/`、`docs/evaluations/`**：审计与评估输出。

## 8. 反例速查

```text
✅ src/wiki/core/paths.py        # 三层切分
✅ tests/test_wiki/test_paths.py # 测试镜像
✅ .index/staging/<draft>.md     # 单一职责子目录

❌ src/wiki/paths.py             # 扁平化（AGENTS.md 已废弃）
❌ tests/test_core.py            # 未镜像子包
❌ .index/lint_cache_and_staging # 多类混用
❌ ~/.config/ruflo-kb/<project>/project.json  # 用户与项目混淆
```

## 9. Lint / 校验脚本

- 本规范**目前无自动 lint**（目录布局变动属于低频决策）。
- 每个 commit 由 plan-audit / code-review 检查"新顶级目录是否已 ADR"；
  后续路线 L-2 可补 `scripts/check_top_level_dirs.py` 自动化。