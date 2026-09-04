# ruflo-kb 安全整改实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Each task ends with a test gate and one logical commit.

**Goal:** 在保持现有行为和脏工作树不受影响的前提下，修复已确认的时间 helper 重复、测试启动覆盖不足、测试 stub 污染、文档同步和 CI 基础设施问题。

**Architecture:** 先做只读盘点并冻结基线，再按独立任务逐项落地。所有 hash 调用按语义保留；只抽取已证明等价的 helper。测试隔离覆盖进程全局状态和导入缓存，CI 当前只承诺 Python 3.11–3.13。

**Tech Stack:** Python 3.11+, pytest, FastAPI TestClient, ruff, GitHub Actions。

**Spec:** `AGENTS.md`、`docs/environment/SETUP.md`、`docs/guides/wiki-spec.md`、本计划的终审审计结论。

## Global Constraints

- 不改 Wiki v2 数据模型、LanceDB/pyarrow 版本和 `requires-python >=3.11`。
- 不引入 mypy strict；保留现有“不引入 mypy”的项目决策。
- 不把不同用途的 hash 强行统一；完整性 hash、ID hash、缓存 key、内容指纹分别保持原契约。
- 不修改无关脏文件；执行前后必须记录 `git status --short`。
- 不把 `.git/hooks/pre-commit` 当作可提交文件；它是本机安装产物。
- 每个任务遵循 RED → GREEN → 全量回归 → 独立 commit；失败时只回滚当前任务 commit。

## 唯一执行顺序

| 顺序 | 任务 | 依赖 | 放行条件 |
|---|---|---|---|
| 0 | 基线与调用点盘点 | 无 | inventory、测试基线、脏文件清单已记录 |
| 1 | 时间 helper 抽取 | 0 | 时间测试和全量测试通过 |
| 2 | retry 语义盘点与最小抽取 | 0 | 仅等价调用点迁移，或明确不迁移 |
| 3 | Server lifespan 测试 | 0 | 无真实网络/用户目录副作用 |
| 4 | stub 隔离试点与分批迁移 | 0、3 | 试点通过后才扩大范围 |
| 5 | 文档同步与 hook 安装器测试 | 0、4 | body 同步规则和临时目录测试通过 |
| 6 | CI 3.11–3.13 与 coverage | 1–5 | clean install、三版本 CI 配置和 coverage 基线通过 |

任务 0 的只读盘点可并行；任务 1–6 的代码变更串行。不得使用旧计划中混用 P0-A/P0-B、B1/B2/B3 的编号。

## Task 0: 基线、审计和调用点 inventory

**Files:** Create `docs/superpowers/audits/2026-09-04-risk-remediation-inventory.md`；不修改代码。

### Steps

- [x] 记录 `git status --short`、`git log --oneline -8` 和当前测试基线。
- [x] 盘点所有 `_now_ms` 定义及 import 方：`rg -n "^def _now_ms|from .* import _now_ms|_now_ms\(" src tests`。
- [x] 盘点所有 hash 调用：`rg -n "hashlib\.(md5|sha256)|hexdigest\(\)\[:[0-9]+\]" src scripts tests`；逐条标注算法、编码、归一化、长度、用途和兼容性。
- [x] 盘点 retry loop，确认是异常重试、队列填充、轮询还是搜索循环；不得按 `for range` 形状直接迁移。
- [x] 盘点 `sys.modules` 写入，区分 collection/import-time stub、runtime stub 和测试自身动态模块。
- [x] 盘点 provider registry、`Path.home()`、`Path.cwd()`、embedding singleton 和 cleanup task 的状态入口。
- [x] 将盘点结果、排除项、测试基线和脏文件摘要写入 `docs/superpowers/audits/2026-09-04-risk-remediation-inventory.md`，固定以下表头：`kind | path:line | current behavior | proposed action | compatibility risk | test gate`；若基线不是 3716 passed，停止后续任务并解释差异。

**Acceptance:** inventory 完整；没有未解释的 caller；未修改任何代码。

## Task 1: 只抽取时间 helper，hash 仅做语义等价迁移

**Files:** Create `src/lib/time.py`、`tests/test_lib/test_time.py`；Modify 仅 inventory 证明等价的 5 个 `_now_ms` 定义及直接 import 方。不得因算法相同而修改用途不同的 hash 调用。

**Interface:** `now_ms() -> int`、`now_iso(*, utc: bool = True) -> str`、`now_aware() -> datetime.datetime`、`ms_to_dt(ms: int) -> datetime.datetime`、`dt_to_ms(dt: datetime.datetime) -> int`。

### Steps

- [x] 先写并运行 RED 测试：Unix ms 为 `int`、UTC aware datetime、毫秒 round-trip、naive UTC 转换、生产代码无 `_now_ms` 定义。
- [x] 实现最小 helper；`now_ms()` 必须返回 `int`，不得返回 `datetime`。
- [x] 只迁移语义完全相同的 `_now_ms` caller。
- [x] 运行 `PYTHONPATH=. pytest tests/test_lib/test_time.py -v` 和 `PYTHONPATH=. python -m pytest --import-mode=importlib`。
- [x] 提交：`refactor(lib): extract time primitives`。

**Acceptance:** 无生产 `_now_ms`；`now_ms() -> int`；全量测试通过；未改变 persisted ID、完整性 hash 或 fingerprint 长度。

## Task 2: retry 只处理真实同步异常重试

**Files:** 若 inventory 找到可安全抽取的真实同步异常重试点，则 Create `src/lib/retry.py` 和 `tests/test_lib/test_retry.py`；否则只在 inventory 中记录关闭理由，不创建文件。Modify `src/lib/write_hooks.py` 仅当迁移后保留原 5 次 PermissionError、sleep、fallback 行为。Do not modify `src/pipeline/retry.py`、queue advance、worker slot-filling、搜索或轮询循环。

**Interface:** `RetryExhausted` 暴露 `attempts: int` 和 `last_exc: BaseException`；`retry_with_backoff` 接受无参 callable，并提供 `max_attempts: int`、`base_delay_s: float`、`max_delay_s: float`、`backoff: float`、`retry_on: tuple[exception types]` 和可注入的 `sleep(seconds: float)`，返回 callable 结果或抛出 `RetryExhausted`。

### Steps

- [x] 测试成功重试、耗尽时保留最后异常、非 retryable 异常只执行一次、`max_attempts < 1` 抛 `ValueError`、sleep 可注入；先确认 RED。
- [x] 仅当 Task 0 找到语义等价的真实同步异常重试 caller 时，实现最小同步 helper；若没有，记录“无安全迁移点”并关闭本 Task，不新增抽象，不提供 decorator API。
- [x] 逐个迁移已证明等价的同步异常重试；queue `advance()` 循环不得迁移。
- [x] 运行相关原子写测试、server smoke test 和全量测试。
- [x] 提交：`refactor(lib): add bounded sync retry helper`。

**Acceptance:** `src/pipeline/retry.py` 不变；migrated caller 的尝试次数、异常类型、sleep、fallback 和返回值与迁移前一致。

## Task 3: FastAPI lifespan 真实启动/关闭测试

**Files:** Modify `tests/test_server/conftest.py`、`AGENTS.md`、`CLAUDE.md`；Create `tests/test_server/test_app_lifespan.py`。

### Isolation contract

fixture 必须隔离并在 teardown 后恢复 `RUFLO_PROJECT_ROOT`、CWD、HOME/user config/cache、provider registry、embedding singleton、相关环境变量和 background task。远程 provider、health check、sentence-transformers 必须 stub/monkeypatch，测试不得访问真实网络。

### Steps

- [x] 用 `<root>/.llm-wiki/project.json` 创建真实 KB marker，不只创建 `<root>/wiki/`。
- [x] 写 3 个测试：启动后 `/health`；真实 marker 可 discovery；退出 TestClient 触发 shutdown 且全局状态恢复。
- [x] 先确认 RED，再加入隔离 fixture：`monkeypatch.chdir(tmp_path)`、临时 HOME/config/cache、singleton 原值保存恢复。
- [x] 对 provider construction、embed、health check、close 使用可断言 stub，并断言网络调用为 0。
- [x] 运行新测试、原 `tests/test_server/` 全集、全量测试；再执行 `$cleanRoot = Join-Path $env:TEMP "ruflo-kb-lifespan-smoke"; New-Item -ItemType Directory -Force $cleanRoot | Out-Null; python -m src.cli serve --project-root $cleanRoot --port 19829`，请求 `/health` 后终止进程并删除该临时目录。
- [x] 提交：`test(server): cover real lifespan lifecycle`。

**Acceptance:** 新测试 3/3 通过；server 原测试和 clean temp root smoke 通过；不读写真实用户 registry；文档描述准确。

## Task 4: sys.modules 隔离试点，再分批迁移

**Files:** 首批 Modify `tests/test_lib/conftest.py`、Create `tests/test_lib/test_stub_isolation.py`；后续按以下固定批次修改其余含 stub 的 conftest；最后按事实更新 `docs/environment/SETUP.md` §4。

| 批次 | 文件 |
|---|---|
| A | `tests/test_agent/conftest.py`、`tests/test_collector/conftest.py`、`tests/test_lib/conftest.py`、`tests/test_project/conftest.py`、`tests/test_vector/conftest.py` |
| B | `tests/test_cli_ext/conftest.py`、`tests/test_e2e/conftest.py`、`tests/test_eval/conftest.py`、`tests/test_mcp_server/conftest.py`、`tests/test_scripts/conftest.py` |
| C | `tests/test_kc/conftest.py`、`tests/test_knowledge/conftest.py`、`tests/test_llm/conftest.py`、`tests/test_permissions/conftest.py`、`tests/test_pipeline/conftest.py` |
| D | `tests/test_searcher/conftest.py`、`tests/test_server/conftest.py`、`tests/test_sync/conftest.py`、`tests/test_wiki/conftest.py` |

### Isolation contract

fixture 对受影响模块做精确 snapshot/restore，覆盖 key 不存在、原模块存在、stub 已存在和 import 失败。import-time stub 不得假设 function scope 足够；需要时用 subprocess 验证独立 import boundary。

### Steps

- [x] 写有效测试：fixture 内 stub 生效；fixture 后恢复原模块/不存在状态；fixture 抛异常仍恢复；dependent module 已缓存时仍能识别污染；subprocess import 结果符合预期。禁止 `or True`、空断言和无条件跳过。
- [x] 先确认 RED，只迁移 `test_lib/conftest.py`。
- [x] 运行 `PYTHONPATH=. python -m pytest tests/test_lib/ --import-mode=importlib -q`。
- [x] 试点通过后，再分批迁移其余 conftest；每批执行目录测试和全量测试。
- [x] 所有 import-time 依赖有独立边界证明后，才删除 module-level `setdefault`。
- [x] 按 A、B、C、D 顺序逐批提交：`test: isolate dependency stubs batch A`、`test: isolate dependency stubs batch B`、`test: isolate dependency stubs batch C`、`test: isolate dependency stubs batch D`。

**Acceptance:** snapshot/restore 测试有效；不存在 stub 残留；全量测试通过；SETUP §4 只删除已被证明失效的警告。

## Task 5: 文档同步与本机 hook 安装器

**Files:** Modify `scripts/setup_git_hooks.py` 使 hook 生成接收显式 repo/hooks 目标路径；Create `tests/test_lib/test_setup_git_hooks.py`；先修复 `AGENTS.md`/`CLAUDE.md` 当前 body 差异；`.git/hooks/pre-commit` 仅为 local-only 产物。

### Steps

- [x] 测试临时目录：位置正确、内容包含两个检查、二次生成字节相同、支持的平台权限正确、文档不一致时按“拦截”策略非零。
- [x] 测试不得依赖 `GIT_DIR` 改变脚本内部硬编码路径。
- [x] 运行 hook installer 测试；全仓 `ruff check src tests` 在 Task 6 完成收口并通过。
- [x] 本计划固定采用“拦截”策略；运行 `python scripts/setup_git_hooks.py` 前先确认 AGENTS/CLAUDE body 已同步；不提交 `.git/hooks`。
- [x] 提交：`fix(hooks): make local hook installation testable`。

**Acceptance:** 临时目录测试通过；hook 不修改无关脏文件；当前文档 body 同步；`.git/hooks` 不出现在 Git 交付清单。

## Task 6: CI 3.11–3.13 与 coverage 基线

**Files:** Modify `.github/workflows/quality.yml`、`pyproject.toml`；除非 Codecov 权限和 token 已确认，不新建独立 workflow。

### Steps

- [x] 在 clean environment 执行 `pip install -e ".[dev]"`，确认 `pytest-cov` 可用。
- [x] 运行 `python -m pytest --import-mode=importlib --cov=src --cov-report=term-missing`，把真实 baseline 写入 inventory；required threshold 固定为 `floor(baseline * 10) / 10 - 1.0` 个百分点，并将计算后的具体数值写入 workflow，同一 commit 不允许只写变量或“待定”。
- [x] workflow 使用 matrix `[3.11, 3.12, 3.13]`；3.14 不列入 required matrix，也不宣称已支持。
- [x] coverage 上传只执行一次；token 缺失时按 owner 决策处理，不得让测试 job 假绿。
- [x] 运行 YAML 静态检查（若仓库已有工具则使用）和 `ruff check src tests`。
- [x] 提交：`ci: test supported Python matrix with coverage`。

**Acceptance:** clean install 成功；三个版本执行同一测试命令；workflow 写入由 baseline 计算出的具体 coverage 阈值且低于 baseline 1 个百分点；ruff 通过。3.14 经依赖兼容性验证后再单独加入计划。

## 两轮终审记录

### Round 1: 全面漏洞审计（已完成）

- **P0**：任务 DAG 与编号混用 → 已改为唯一执行顺序。
- **P0**：hash 用途和截断长度不同 → 改为逐调用点等价证明，不再全局统一。
- **P0**：lifespan 只隔离 project root → 加入 CWD、HOME、registry、singleton、网络和 teardown 恢复。
- **P0**：function-scoped `sys.modules` 不足以覆盖 import cache → 加入分类、snapshot/restore 和 subprocess boundary。
- **P0**：Goal 要求 3.14、CI 只跑 3.11–3.13 → 当前承诺明确为 3.11–3.13。
- **P1**：queue filling loop 被误称 retry → 明确禁止迁移。
- **P1**：隔离测试存在 `or True` → 明确禁止无效断言。
- **P1**：hook 测试无法控制硬编码路径 → 要求显式目标路径。
- **P1**：`.git/hooks` 不能作为普通提交回滚 → 改为 local-only 安装产物。
- **P1**：coverage 依赖缺失 → 要求 clean install 和 baseline 先行。

### Round 2: 压力测试（已完成）

| 场景 | 失效方式 | 加固 |
|---|---|---|
| 干净 clone | discovery marker 不完整 | 使用真实 `.llm-wiki/project.json` |
| registry 已存在 | 测试读写真实用户配置 | 临时 HOME/config/cache + registry reset |
| optional embedding 缺失 | lifespan 访问网络或 fallback 不稳定 | stub provider/embed/health，断言网络调用为 0 |
| collection 已缓存 stub | teardown 后依赖仍指向 stub | import-time 分类 + subprocess boundary |
| queue 满载 | retry 改变 worker slot 语义 | 禁止迁移 queue advance loop |
| 脏工作树 | hook/sync 触碰无关文件 | local-only hook、先做 body 同步、记录 status |
| CI 缺 pytest-cov | `--cov` 直接失败 | 加入 dev 依赖并 clean install |
| 3.14 依赖不可装 | 目标和 CI 不一致 | 当前不承诺 3.14 |
| 中途失败 | 大批 conftest 一次性破坏 collection | 试点 + 分批独立 commit |

### Human review / re-review

已按当前代码、脏状态和 `361273ee` V5 修复复核。上述 P0/P1 已写入计划；编码前仍必须完成 Task 0 inventory，inventory 与计划不一致时重新审计，不得直接实施。

## 最终放行门

1. Task 0 inventory 完整，所有 hash caller、retry loop、stub 和全局状态入口均有归类。
2. 当前测试基线已记录且无未解释失败。
3. `AGENTS.md` 与 `CLAUDE.md` body 同步策略已确定。
4. 3.11–3.13 是当前支持矩阵；3.14 不出现在 required acceptance 中。
5. Task 3/4 隔离测试证明不访问真实网络、不污染用户目录、不残留 stub。
6. 每个任务都有真实 RED/GREEN 测试、量化 acceptance 和独立回滚点。

未满足任一条件：状态为 `blocked`，回到计划审计，不进入代码实现。

## 回滚

- Task 1：revert 时间 helper 和直接 caller。
- Task 2：revert retry helper 及等价 caller；`src/pipeline/retry.py` 不动。
- Task 3：revert 测试与文档；不删除用户数据。
- Task 4：按批次 revert；原 conftest 保留到对应批次稳定。
- Task 5：删除本机 `.git/hooks/pre-commit` 即停用；不操作 `.git` 之外文件。
- Task 6：revert workflow 和 `pyproject.toml`；保留测试代码。

## Completion evidence

- 每个任务一个逻辑 commit，Task 4 每批一个 commit。
- 每步记录测试命令和结果；最终提供全量 pytest、ruff、coverage baseline/threshold、clean server smoke evidence。
- 更新 `.superpowers/sdd/progress.md`；不提交 `.git/hooks/pre-commit`。

## 最终验收记录（2026-09-04）

- **结论：实施完成，达到进入 CI 验证和上线评审的标准。** Task 0–6 的实施项已完成并已勾选；未修改 Wiki v2 数据模型、LanceDB/pyarrow 版本或 3.14 支持承诺。
- **代码提交证据：** `8e7a85b5`、`82ecc34d`、`450c039d`、`39f5477b`、`61b6eae6`、`30b44cc5`、`97efc7de`；每个逻辑任务均有独立提交，Task 4 按批次保留隔离提交。
- **回归证据：** 隔离环境全量测试 `3733 passed, 45 warnings`；最终 coverage `78.45%`，CI 固定阈值 `77.4%`；`ruff check src tests` 通过；workflow YAML 静态解析通过；真实临时项目 lifespan `/health` smoke 通过。
- **CI 证据：** workflow 已配置 Python `3.11`、`3.12`、`3.13` 同一 coverage-gated 测试命令，coverage artifact 只从 `3.12` 上传一次；3.14 未列入 required matrix。当前本机直接回归证据为 Python 3.12，3.11/3.13 需以 CI 实际运行结果完成跨版本确认。
- **环境限制：** `graphify update .` 仍受本机 uv trampoline canonicalize 错误阻塞；未修改全局工具或缓存，该问题不影响本次代码和测试验收。
- **交付边界：** `.git/hooks/pre-commit` 为本机 local-only 产物，不进入 Git 交付；现有无关脏文件保持不变。
