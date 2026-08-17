# Plan: 模块规范性与统一化改造

> 数据来源：`模块规范性与统一化差距评估.md`（基于图谱 23,384 节点 / 62,295 边 + 目录树 + 源码取证）
> 审查过程：graphify 深度查询（CLI 入口/配置层/脚本耦合/文档结构）+ grill-me 五轮压力测试
> 涉及项目：`D:\5-Project\2026814`（ruflo-kb，id `D-5-Project-2026814`）

status: planned
branch: feature/2026-08-26-module-standardization

## Goal

将 ruflo-kb 从"架构骨架 A 级、入口/编排/整洁 C 级"的失序状态，统一为四层（API→entry→core→internal）边界清晰、入口规范、配置可审计、脚本无复制式同构的健康状态。

**非目标：**
- 不改变管线语义（Collector→Analyzer→Generator→Writer 行为零变更）
- 不引入新业务功能
- 不重构 pipeline 内部的 LLM 调用路径
- 不修改向量存储 / LanceDB 维度

## 依赖关系

```
P0-A (CLI 注册) ──→ P0-B (中央配置模块) ──→ P1-A (BatchRunner 收编) ──→ P1-B (根目录清理)
                                                                       │
                                                                       └─→ P2-A (文档同步) ──→ P2-B (superpowers 归档) ──→ P3 (公共层边界)
```

P0-A → P0-B → P1-A 严格串行（P0-B 依赖 P0-A 的 CLI 入口做 `ruflo config list`；P1-A 依赖 P0-B 的配置接口获取预算/阈值）。P1-B 与 P2-A/P2-B 可并行。P3 最后做。

## Tasks

### Task 1: P0-A — 注册 `ruflo` 命令入口

将 `src/cli.py:main()` 注册为 `ruflo` 命令，使现有 20+ 子命令（project/schema/health/heat/cache/relations/fields/tags/stubs/dedup/lint/metrics/llm-providers/quality/vision/serve/mcp/research/templates/atomic/budget/completions）获得规范入口。

- **Files:**
  - `pyproject.toml` — 补 `[project.scripts]` 节
  - 无其他文件改动

- **实现：**
  ```toml
  [project.scripts]
  ruflo = "src.cli:main"
  ```
  仅此一行。`platformdirs>=4.0` 已在 `[project.dependencies]`；`auto_register_on_first_run` 在新环境静默返回空列表（`discover_existing_kbs` 找不到则跳过，`except Exception` 兜底），不会崩溃。

- **验收：**
  1. L1：`pip install -e .` 安装后 `ruflo --help` 列出全部子命令
  2. `ruflo project list` 正常工作（无注册表时返回空列表）
  3. `ruflo health --help` 输出参数说明
  4. 现有 CLI 使用方式（`python -m src.cli`）不受影响

- **风险：**
  - 无。这是最小改动的标准 pip 注册。

- **Status:** pending

---

### Task 2: P0-B — 完整 `BaseSettings` 中央配置模块

引入 `pydantic-settings`，创建 `src/config.py`（`Settings` 类），将全项目 28 处 `os.environ` 分两批迁移。**禁止 `@lru_cache` 缓存 Settings 实例**，每次 `Settings()` 实时读 env，确保 `src/pipeline/shadow.py` 的运行时热切换（`RUFLO_PIPELINE_MODE`/`RUFLO_SHADOW_MODE` set/pop）不受影响。

- **Files:**
  - `pyproject.toml` — 新增 `pydantic-settings` 依赖
  - `src/config.py` — 新建中央配置模块（`Settings` dataclass + 字段声明 + 默认值 + 说明文档）
  - `src/llm/registry.py` — 替换 `os.environ.get("OPENAI_API_KEY")` 等 3 处
  - `src/llm/provider_factory.py` — 替换 1 处
  - `src/llm/types.py` — 替换 1 处
  - `src/pipeline/generator.py` — 替换 `RUFLO_MAX_SOURCE_CHARS` 1 处
  - `src/pipeline/prefilter.py` — 替换 `RUFLO_SANITIZER_SKIP_LLM` 1 处
  - `src/pipeline/shadow.py` — 保留 `os.environ` 直接读写（热切换），但 `Settings().pipeline_mode` 作为只读快照
  - `src/pipeline/_pipeline_common.py` — 替换 `RUFLO_JSON_DEBUG_DIR` 1 处
  - `src/research/runner.py` — 替换 `TAVILY_API_KEY` 1 处
  - `src/cli.py` — 替换 `RUFLO_CONFIG_DIR` 1 处
  - `src/cli_ext/wiki_templates_cmd.py` — 替换 `EDITOR`/`VISUAL`/`RUFO_NONINTERACTIVE` 3 处
  - `src/wiki/storage/page_writer.py` — 替换 `RUFLO_TAXONOMY_VALIDATION` 1 处
  - **第二批（实验分支，本次不动）：** `src/knowledge/storage/facade.py`（7 处 `STORAGE_BACKEND`/`DATABASE_URL`/`S3_*`，等实验分支稳定后再纳入）

- **配置域划分：**
  | 域 | 变量 | 迁移批次 |
  |---|---|---|
  | CLI | `RUFLO_CONFIG_DIR` | 第一批 |
  | LLM 提供者 | `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`RUFLO_LLM_PROVIDER_ENV` | 第一批 |
  | Pipeline 行为 | `RUFLO_MAX_SOURCE_CHARS`、`RUFLO_SANITIZER_SKIP_LLM`、`RUFLO_JSON_DEBUG_DIR`、`RUFLO_TAXONOMY_VALIDATION` | 第一批 |
  | Pipeline 热切换 | `RUFLO_PIPELINE_MODE`、`RUFLO_SHADOW_MODE` | 第一批（只读，写路径保留 `os.environ`） |
  | 外部服务 | `TAVILY_API_KEY` | 第一批 |
  | 编辑器 | `EDITOR`、`VISUAL`、`RUFO_NONINTERACTIVE` | 第一批 |
  | 存储后端 | `STORAGE_BACKEND`、`DATABASE_URL`、`S3_*`（7 处） | **第二批（暂不动）** |

- **`src/config.py` 设计：**
  ```python
  # src/config.py — 中央配置模块（非 @lru_cache，每次实时读 env）
  from pydantic_settings import BaseSettings

  class Settings(BaseSettings):
      # CLI
      config_dir: str = ""  # RUFLO_CONFIG_DIR

      # LLM providers
      openai_api_key: str = ""      # OPENAI_API_KEY
      anthropic_api_key: str = ""   # ANTHROPIC_API_KEY
      llm_provider_env: str = ""    # RUFLO_LLM_PROVIDER_ENV

      # Pipeline behavior
      max_source_chars: int = 16000  # RUFLO_MAX_SOURCE_CHARS
      sanitizer_skip_llm: bool = False  # RUFLO_SANITIZER_SKIP_LLM
      json_debug_dir: str = ""       # RUFLO_JSON_DEBUG_DIR
      taxonomy_validation: str = "warn"  # RUFLO_TAXONOMY_VALIDATION

      # External services
      tavily_api_key: str = ""       # TAVILY_API_KEY

      # Editor
      editor: str = ""               # EDITOR
      visual: str = ""               # VISUAL
      noninteractive: bool = False   # RUFO_NONINTERACTIVE

      # Storage backend (experimental — 第二批)
      storage_backend: str = "filesystem"
      database_url: str = ""
      s3_endpoint_url: str = ""
      s3_bucket: str = ""
      s3_access_key: str = ""
      s3_secret_key: str = ""

      model_config = {"env_prefix": ""}  # 变量名与 env 同名
  ```

- **验收：**
  1. L1：`pytest --import-mode=importlib` 全绿
  2. L2：`python -m src.cli serve --port <free>` + `curl /health` 返回 200
  3. L4 影子验证：`RUFLO_PIPELINE_MODE=legacy RUFLO_SHADOW_MODE=true python -m src.cli serve` 启动后，`os.environ` 热切换仍生效（`shadow.py` set/pop 无报错）
  4. 手动验证：`Settings().openai_api_key` 与 `os.environ.get("OPENAI_API_KEY")` 值一致
  5. 新增 `ruflo config list` 子命令，打印全量配置清单（含默认值 + 所在文件引用）

- **风险：**
  - `src/pipeline/shadow.py` 的 `os.environ` 写操作（`os.environ["RUFLO_PIPELINE_MODE"] = ...`）必须保留——`Settings()` 只读，不写入 env。需要确保 shadow.py 不引入 `from src.config import Settings` 然后只读快照。
  - `src/knowledge/storage/facade.py` 的 7 个 S3 变量暂不迁移，标注为"第二批（实验分支）"。

- **Status:** pending

---

### Task 3: P1-A — `BatchRunner` 框架收编 `scripts/`

> ⚠ 本任务风险最高。`scripts/batch_executor.py`（1004 行）含六态崩溃续跑状态机、三阶段原子流程、预算暂停、整批门禁复核，且 `tests/test_scripts/test_batch_executor.py` 有 `os._exit(137)` 崩溃注入测试资产。**执行顺序：先拆引擎/CLI 壳 → 提取门禁真源 → 定义 BatchRunner 抽象 → 填充实现 → 逐一收编其他脚本。** 每步独立 commit，严禁一次性大改。

- **子任务 3a：提取门禁五项为共享真源**
  - 从 `scripts/batch_executor.py` 提取 `_gate_fields`、`_gate_tags`、`_gate_lint`、`_gate_reconcile`、`run_precommit_gate` 到 `src/wiki/features/batch_gate.py`
  - 保持函数签名不变，仅改 import 路径
  - `scripts/batch_executor.py` 改为 `from src.wiki.features.batch_gate import run_precommit_gate`
  - 测试：`test_batch_executor.py` 只改 import 路径，断言零改动

- **子任务 3b：拆 `batch_executor.py` 引擎与 CLI 壳**
  - 引擎逻辑（`run_batch`、`_generate_raw`、`_commit_raw`、`_upsert_batch_vectors`、`_rerun_gate_batch`、`_auto_tag_ugc`、`_estimate_batch_cost`、`_git_snapshot`、`_is_immutable_source`、`_crash_at`、`_fake_generate`、`_update_fail_streak`、`_set_batch_status`、`_resolve_paths`、`_resolve_provider`）→ `src/orchestrator/batch_runner.py`
  - CLI 壳（`main()`、argparse、`sys.exit(main())`）→ 留在 `scripts/batch_executor.py` 约 30 行
  - 引擎部分注册为 `BatchRunner` 子类方法

- **子任务 3c：定义 `BatchRunner` 抽象基类**
  - 位置：`src/orchestrator/batch_runner.py`
  - 契约：
    ```python
    class BatchRunner(ABC):
        @abstractmethod
        def load_batch(self, batch_id) -> Batch: ...
        @abstractmethod
        def run_one(self, item) -> Result: ...

        # 框架方法（可覆盖）
        def gate(self, batch) -> GateReport: ...      # 复用 batch_gate.py
        def execute(self, batch, dry_run=False): ...   # 状态机 + 并发 + 预算
        def commit(self, batch): ...                   # 复用 commit_ingest
        def rollback(self, batch): ...                 # 复用 rollback_batch
        def emit_metrics(self): ...                    # 复用 metrics
    ```
  - `execute()` 内部预留状态机生命周期钩子（`_on_phase_start`/`_on_phase_end`）以支持崩溃注入测试

- **子任务 3d：收编其他脚本为薄 CLI 包装**
  | 原脚本 | 目标子命令 | 包装方式 |
  |---|---|---|
  | `batch_ingest`、`batch_generate`、`batch_build`、`pilot_ingest`、`phase3_accept`、`phase4_batch`、`phase5_accept`、`accept_batch` | `ruflo batch run` | 继承 `BatchRunner`，实现 `run_one` |
  | `batch_gate_check`、`batch_gate_v3`、`diagnose_batch_gate` | 并入 `BatchRunner.gate()` | 调用 `batch_gate.py` |
  | `batch_commit`、`rollback_batch` | 并入 `BatchRunner.commit/rollback` | 调用 `batch_state.py` |
  | `plan_gap_first_batch`、`plan_reingest_batches`、`build_reingest_backlog` | `ruflo batch plan` | 继承 `Planner` 基类 |
  | 5 × `migrate_*` | `ruflo migrate` | 继承 `Migration` 基类（带 `--dry-run`/`--verify`） |
  | 3 × `audit_*`、`quality_check_wiki` | `ruflo audit` | 继承 `Auditor` 基类 |
  | `fix_mojibake_sources`、`cleanup_*`、`normalize_sources`、`ndg_calibrate`、`sync_wiki_spec`、`rebuild_index`、`stress_test_ingest`、`aggregate_synthesis`、`ingest_novel_wiki_*`、`setup_git_hooks` | `ruflo util` 或 `tools/` | 收编为子命令或保留为运维工具 |

- **验收：**
  1. L1：`pytest --import-mode=importlib` 全绿
  2. **L3 强制：** `tests/test_scripts/test_batch_executor.py` 崩溃注入测试全套通过（`os._exit(137)` 在 generate/gate/cascade/commit 四阶段）
  3. `scripts/batch_executor.py` 仅剩 ~30 行 CLI 壳
  4. `src/wiki/features/batch_gate.py` 被至少 2 个调用者引用（消除单点复制）
  5. `ruflo batch run --help` 正常工作
  6. `scripts/batch_ingest.py` 等薄脚本可通过 `python scripts/batch_ingest.py` 或 `ruflo batch run` 两种方式调用（兼容过渡期）

- **风险：**
  - `test_batch_executor.py` 的崩溃注入测试依赖 `scripts.batch_executor` 的模块路径——平移后可能因 `sys.path.insert(0, ...)` 或 `sys.modules` 缓存导致测试找不到模块。方案：`test_batch_executor.py` 同时测试 `scripts.batch_executor`（CLI 壳）和 `src.orchestrator.batch_runner`（引擎），确保两者都覆盖。
  - 状态机生命周期钩子必须在 `BatchRunner` 的第一版就预留，否则后续加崩溃注入测试时需要改抽象接口。

- **Status:** pending

---

### Task 4: P1-B — 根目录清理

将根目录下的 11 个诊断/草稿文件移入 `tools/` 或删除。

- **Files:**
  | 文件 | 处置 |
  |---|---|
  | `diag_b4.txt` | 删除（诊断产物，无保留价值） |
  | `diag_p7.py` | 删除（诊断产物） |
  | `diag_p7_out.txt` | 删除（诊断产物） |
  | `env.example` | 移入 `tools/` |
  | `fix_backtick.py` | 删除（已修复，git 历史可追溯） |
  | `fix_backtick2.py` | 删除（同上） |
  | `metrics.db` | 删除（运行时产物，不应在根目录） |
  | `registry.json` | 确认是否仍在用 → 在用则移入 `.llm-wiki/` 或 `tools/` |
  | `server.log.err` | 删除（日志产物） |
  | `test_llm_response.py` | 移入 `tests/` 对应目录 |
  | `test_reingest.py` | 移入 `tests/` 对应目录 |

- **验收：**
  1. 根目录 `ls` 只保留项目固有文件（`pyproject.toml`、`src/`、`tests/`、`scripts/`、`docs/`、`web/`、`README.md` 等）
  2. `git log --oneline` 可追溯被删除文件
  3. `pytest` 全绿（确认 `registry.json` 的移动不影响 `GlobalRegistryStore` 加载）

- **Status:** pending

---

### Task 5: P2-A — CLAUDE.md / AGENTS.md 双文件强制同步

> 用户选择 D：保留双文件，加 pre-commit 钩子强制哈希一致。

- **Files:**
  - `.husky/pre-commit` 或 `scripts/setup_git_hooks.py` 扩展
  - `.gitignore`（无需改动）

- **实现：**
  - 在 `scripts/setup_git_hooks.py`（已有 Hook 安装脚本）中新增 pre-commit 校验：
    ```python
    # 校验 CLAUDE.md 与 AGENTS.md 的 SHA256 哈希一致
    hash1 = hashlib.sha256(Path("CLAUDE.md").read_bytes()).hexdigest()
    hash2 = hashlib.sha256(Path("AGENTS.md").read_bytes()).hexdigest()
    if hash1 != hash2:
        print("ERROR: CLAUDE.md and AGENTS.md differ — update both before commit")
        sys.exit(1)
    ```
  - 首次运行 `python scripts/setup_git_hooks.py` 安装/更新钩子

- **两条同步规则：**
  1. 修改 `CLAUDE.md` 时，必须同步修改 `AGENTS.md`（反之亦然）
  2. 如果两文件内容完全一致，可考虑 `CLAUDE.md` 改为指向 `AGENTS.md` 的指针（一行），但需要在 `claude` CLI 上实测确认

- **验收：**
  1. 故意修改 `CLAUDE.md` 不更新 `AGENTS.md` → `git commit` 被阻止
  2. 同步修改后 → `git commit` 通过
  3. 现有两个文件保持等长，无需立刻合并

- **Status:** ✅ `96a9466d`（正文同步校验 + pre-commit 钩子）

---

### Task 6: P2-B — `docs/superpowers` 72 文档归档

- **实现：**
  1. 按最后修改时间分档：
     ```
     find docs/superpowers -type f -name "*.md" -mtime -30  → 保留
     find docs/superpowers -type f -name "*.md" -mtime +90  → 归档至 docs/archive/superpowers/
     find docs/superpowers -type f -name "*.md" -mtime 30-90 → 列出清单人工确认
     ```
  2. 归档后，`docs/superpowers/` 仅保留当前活跃（<30 天）的规划文档 + `PLAN_TEMPLATE.md`
  3. 在 `docs/archive/` 根目录加 `README.md` 说明"此目录为历史规划归档，不反映当前状态"

- **验收：**
  1. `docs/superpowers/` 文档数从 72 降至 ≤15（含 `PLAN_TEMPLATE.md`）
  2. `docs/archive/superpowers/` 已归档文件可访问
  3. `.superpowers/sdd/progress.md` 仍有链接指向 `docs/superpowers/`——更新这些链接指向归档后的位置

- **Status:** ✅ `409b0dc2`（73→9 保留，64 归档）

---

### Task 7: P3 — 明确 `lib` / `shared` / `utils` 边界

- **实现：**
  1. `src/shared/` 仅含 `test_helpers.py` → 整体移入 `tests/support/test_helpers.py`，`src/shared/` 删除
  2. 更新所有 `from src.shared.test_helpers import ...` 为 `from tests.support.test_helpers import ...`
  3. 明确写入 `CONTRIBUTING.md` 或 `AGENTS.md`（或两个文件同时）的命名约定：
     - `src/utils/`：纯函数、无副作用的工具（path/slugify/text/similarity/idempotency）
     - `src/lib/`：框架性代码、有副作用的辅助（atomic_ctx/write_hooks/project/context_budget/budgeted）
     - `src/*/core/`：业务领域核心（wiki/core、knowledge/core），不与上面两个桶混淆
  4. `src/utils/` 和 `src/lib/` 各加 `__init__.py` 导出（可选，降低 import 深度）

- **验收：**
  1. `src/shared/` 目录不存在
  2. `tests/` 中 `from tests.support.test_helpers import ...` 可正常导入
  3. `pytest` 全绿
  4. 新写代码遵循命名约定

- **Status:** ✅ `257d7777`（src/shared → tests/support，9 importer 更新）

---

## Audit

### Round 1: pending — 记录 findings 和 fixes

- 所有引用 `src/shared/` 的 import 必须全部更新，否则 P3 会静默 break
- `scripts/batch_executor.py` 引擎拆分后，`test_batch_executor.py` 的崩溃注入路径可能变化——需确认 `os._exit(137)` 在框架级测试中仍能正确触发

### Round 2: pending — 记录 findings 和 fixes

### Human review: pending

### Open risks

1. **P0-B 与 shadow.py 的运行时热切换冲突**（已确认：`Settings()` 实时读 env 不缓存，避免此问题）
2. **P1-A 的崩溃注入测试重写成本**：`test_batch_executor.py` 含 `os._exit(137)` 子进程注入，需框架级预留钩子
3. **P2-A 的双文件同步成本**：每改一处要同步两处，但可以用 `git mv` 把其中一个变成指针 + 软链接（需要实测 agent 工具是否识别）
4. **P3 的 `src/shared/` 删除**：`from src.shared.test_helpers import ...` 分散在多个测试文件中，需 grep 全覆盖

### Rollback

每个 P 的每次 commit 都是可逆的。P0-A 的 `[project.scripts]` 注释掉即恢复。P0-B 的 `src/config.py` 删除 + 恢复 28 处 `os.environ` 即恢复。P1-A 的 git 历史保留 `scripts/batch_executor.py` 原始版本，坏掉可 `git checkout`。P2-A 的钩子删除即可。P3 的 `src/shared/` 保留 git 历史。

## Completion evidence

- **Final commit:** 每个 P 一个独立 commit（`feat(unify): P0-A 注册 ruflo CLI 入口` 等格式）
- **Tests:** 每个任务 TDD：先写测试/验收，再实现，再 commit；每步 `pytest --import-mode=importlib` 全绿
- **Static checks:** 无 linter 约束（项目无 ruff 检查 CI），但 P0-B 的 `pydantic-settings` 类型标注可考虑 `mypy` 检查
- **Documentation updated:**
  - `AGENTS.md` / `CLAUDE.md`（同步更新，P2-A 钩子确保）
  - `.superpowers/sdd/progress.md`（每任务后更新账本）
  - `docs/superpowers/plans/`（本文件）
- **Progress ledger updated:** yes