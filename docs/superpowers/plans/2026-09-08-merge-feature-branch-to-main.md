# 将功能分支分批合并到 main 实施计划

> **执行约束：** 本方案由当前会话按批次执行，不使用子 Agent。默认采用“一个集成分支、一个最终 PR”：批次只用于隔离验证和回滚，全部通过后才一次性进入远端 `origin/main`。

**Goal:** 将当前本地功能分支 `codex/book-series-target` 在 Task 0 实时冻结的提交范围，拆成可审查、可验证、可回滚的批次，最终通过一个 PR 合入远端 `origin/main`。文档中的提交 SHA 只作上次观测记录，执行时不得直接照抄。

**Architecture:** 先从最新 `origin/main` 创建干净集成 worktree，再按提交依赖和业务边界分批 cherry-pick；每批只在自己的测试和验收通过后进入下一批。当前工作区的未提交文件不自动参与迁移，是否纳入必须在 Task 0 单独决定。最终只创建一个 PR，避免为个人项目维护多个长期分支。

**Tech Stack:** Git branches/cherry-pick/PR、Python 3.11+、pytest、项目现有 Wiki/KC/Book 管线、graphify 结构更新。

**Spec:** `docs/superpowers/plans/2026-09-08-prompt-injection-hardening.md`；Book 相关原始方案和验收记录见 `docs/superpowers/plans/`、`.superpowers/sdd/progress.md`。

## Global Constraints

- 不使用 `git reset --hard`、`git clean` 或覆盖用户未提交文件。
- 不从当前脏工作区创建集成分支；集成分支必须从最新 `origin/main` 开始。
- 不把无关的 Book 实验产物、临时目录、`.memory/` 或未跟踪文件混入某个批次。
- 每个批次必须有独立提交范围、测试结果、风险记录和回滚点。
- 全量测试必须使用项目要求的 `PYTHONPATH=.` 和 `--import-mode=importlib`；Python 解释器路径必须在 Task 1 动态发现并记录，不能假设固定路径存在。
- 合并前必须补齐 `mcp`、`pyarrow`、`lancedb` 等测试依赖；只跑局部测试不能作为最终放行证据。
- 摄取安全方案必须保持：system/user 分层、证据门禁、应用控制路径、quarantine、`[no-retry]` 和 `AtomicContext`。
- 未经用户再次明确授权，不执行最终合并、删除分支或修改远端 `main`。
- 本方案的 `main` 统一指远端 `origin/main`；本地 `main` 不作为合并目标，也不在执行中切换或移动。
- “逐批”只表示逐批应用、测试和验收；若用户要求每批实际进入 `main`，必须改为五个独立 PR，不沿用本方案的单 PR 流程。
- 以下命令中的 `$baseSha`、`$sourceSha` 和 `$auditDir` 均指 Task 0 记录的值；跨 PowerShell 调用时必须重新赋值或读取记录，不能依赖上一个 shell 的变量，也不能重新读取未冻结的 live ref。

## 并行子代理执行协议

并行只用于“互不写同一份状态的审查和验证”，不用于并行改写同一个集成分支。所有子代理统一使用 `gpt-5.6-luna`，reasoning effort 为 `medium`，只读审查，不得 push、merge、reset、clean、安装依赖或修改当前工作区。个人项目最多启动两个代理，避免多个代理重复读取同一份计划。

第一轮可同时启动以下两个独立任务：

1. **集成与环境代理**：审查基线冻结、worktree、提交范围、冲突处理、回滚、Python/依赖、测试污染、smoke test 和远端 main 漂移。
2. **安全与简化代理**：审查提示词边界、证据门禁、路径保护、quarantine、`[no-retry]`、AtomicContext、Batch 4.1 元数据归属，以及个人项目的最小流程。

每个代理必须返回：问题等级（P0/P1/P2）、文件/行号证据、失败场景、最小修复建议；不直接改文件。主会话收到结果后统一裁决冲突、修改计划文档，并将有效建议转为验收步骤。只有主会话可以在集成 worktree 执行 cherry-pick、冲突解决、提交、push 前检查和最终合并门。

以下动作必须串行：Task 0 引用冻结 → Task 1/2 环境与基线 → 批次 0 → 批次 1 → 批次 2 → 批次 3 → 批次 4/4.1 → 最终 PR。若需要让代理运行测试，必须给每个代理独立的临时 worktree、独立 `--basetemp` 和独立输出目录；禁止多个代理同时操作同一个 `.index`、`graphify-out`、真实知识库或集成分支。代理只返回审查结论，不负责实现或提交。

## 当前基线

截至 2026-09-08，已确认：

- `origin/main`：`7103a729`。
- 远端功能分支：`origin/codex/book-series-target`，当前已到 `5345fc93`。
- 上次观测的本地功能分支 HEAD：`138cbb22`；其后相对 `a12f2a76` 新增 `0c67af91`、`138cbb22` 两个 Book 提交。执行时仍必须以 Task 0 重新读取的 HEAD 为准。
- 上次观测的本地功能分支相对 `origin/main`：63 个提交；文件数和行数不再作为固定验收数字，Task 0 重新统计。
- 本地 `main`：`ef0aa752`，比 `origin/main` 多 22 个提交，且是功能分支的祖先；它只是本地历史指针，不代表远端合并目标。
- 当前工作区存在大量既有修改和未跟踪文件；这些内容必须单独保存，不得随批次合入。
- 摄取安全两个提交已完成局部测试：受影响模块 1,254 个测试通过。
- 全量测试当前在收集阶段被环境依赖阻塞：缺少 `mcp`，排除后又缺少 `pyarrow`。
- Book 的“代码合并”与“生成内容发布”分开验收：即使代码合并门通过，也不能把未完成的真实 Provider/人工验收写成完整 LLM 内容已发布。

## 批次划分

提交范围按当前线性历史拆为五个迁移批次。实际执行前先用 `git show --stat` 核对每个边界，若某个提交已被拆分或依赖关系变化，停止并重新切批，不强行 cherry-pick。

| 批次 | 提交范围 | 目标 | 放行条件 |
|---|---|---|---|
| 0 | `2e2fcc03` | lineage 与 Wiki 提交基础保护 | lineage/摄取回归通过，数据迁移风险可回滚 |
| 1 | `607c05f5..048b9883` | Wiki-to-Book 基础能力、Web 阅读页、Provider 配置 | Book 基础/API/Web 测试通过 |
| 2 | `275304aa..919d8440` | release 展示、样例、书系数据契约与基础 gate | 书系契约、release、CLI gate 通过 |
| 3 | `fdd5722d..d06e906f` | 书系编译、跨书来源、唯一归属、依赖环和幂等修复 | compiler/lineage/series 回归通过 |
| 4 | `a85886cc..$sourceSha`（上次观测终点 `138cbb22`） | 收尾文档、V4 摄取、profile、Book 审计修复及本次摄取安全整改 | 全量测试、代码 dry-run 和安全缺口关闭 |

说明：范围使用 Git 的三点/双点语义时必须明确。迁移时采用 `git cherry-pick <start>^..<end>`，确保包含起止提交；批次 4 包含本次两个安全提交以及之后的 Book 审计修复，不能只凭提交标题判断其独立性。每批应用前记录集成分支 HEAD，应用后记录实际生成的首尾 SHA，回滚时使用整批 SHA 范围，不使用“单个 batch commit”这一不存在的对象。

## Task 0: 冻结现状并建立迁移清单

**Files:**

- Read: `git status --short`
- Read: `git log --reverse --format="%H %s" origin/main..HEAD`
- Create: `docs/superpowers/plans/2026-09-08-merge-feature-branch-to-main.md`（本方案）
- Read: `.superpowers/sdd/progress.md`

**Interfaces:**

- Produces: 固定的远端 `origin/main` SHA、源功能分支本地 HEAD SHA、本地功能分支远端 SHA、五批提交清单和脏工作区清单。

- [ ] **Step 1: 记录远端和本地引用**

```powershell
git fetch origin main codex/book-series-target
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed; do not use stale refs' }
$currentBranch = (git branch --show-current).Trim()
if ($currentBranch -ne 'codex/book-series-target') { throw "run Task 0 from codex/book-series-target, got: $currentBranch" }
$baseSha = (git rev-parse origin/main).Trim()
$sourceSha = (git rev-parse HEAD).Trim()
$remoteFeatureSha = (git rev-parse origin/codex/book-series-target).Trim()
git merge-base --is-ancestor $baseSha $sourceSha
if ($LASTEXITCODE -ne 0) { throw 'source feature branch is not based on origin/main' }
git rev-list --left-right --count origin/main...HEAD
git show -s --format="%H %s" main
```

执行记录必须明确：`baseSha` 是唯一合并目标；`sourceSha` 是 Task 0 当时的本地功能分支快照；本地 `main` 只读，不参与迁移。文档中旧的 `a12f2a76`/61 提交记录不能替代实时冻结值。

- [ ] **Step 2: 保存脏工作区清单**

```powershell
$auditDir = Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-merge-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $auditDir | Out-Null
git status --short --untracked-files=all | Out-File (Join-Path $auditDir "working-tree-status.txt") -Encoding utf8
git diff --name-only | Out-File (Join-Path $auditDir "working-tree-diff-files.txt") -Encoding utf8
@("baseSha=$baseSha", "sourceSha=$sourceSha", "remoteFeatureSha=$remoteFeatureSha", "auditDir=$auditDir") | Out-File (Join-Path $auditDir "refs.txt") -Encoding utf8
```

清单只用于审计，写在仓库外，不得 `git add`。后续独立 PowerShell 会话必须先从该 `refs.txt` 读取冻结值，并重新设置 `$baseSha`、`$sourceSha`、`$auditDir`；不得依赖上一个会话残留变量。对当前有意义的源码/测试/文档修改逐项标记“纳入本次功能 / 暂缓另行提交 / 明确排除”；默认不把它们混入本次源分支迁移。

- [ ] **Step 3: 核对每个批次的文件范围**

```powershell
git diff --stat $baseSha...$sourceSha
git show --stat --oneline 2e2fcc03
git diff --stat 607c05f5^ 048b9883
git diff --stat 275304aa^ 919d8440
git diff --stat fdd5722d^ d06e906f
git diff --stat a85886cc^ $sourceSha
git diff --name-only $baseSha...$sourceSha
```

最后一个文件清单必须没有 `raw/`、`knowledge/`、`.index/`、`.env`、`secrets`/`credentials` 目录或密钥文件；如确实需要，先从功能分支剔除或单独获得明确授权，不在合并阶段临时放行。

- [ ] **Step 4: 放行判断**

```powershell
if ((git rev-parse HEAD).Trim() -ne $sourceSha) { throw 'local feature HEAD moved; re-freeze sourceSha' }
if ((git rev-parse origin/main).Trim() -ne $baseSha) { throw 'origin/main moved; re-freeze baseSha' }
```

若任一检查失败，停止当前流程并重新冻结引用；不得在旧集成分支上继续追加。远端功能分支只用于记录，不作为本次 cherry-pick 来源；若改为使用远端功能分支，也必须重新冻结并重算范围。若工作区清单中出现本方案文件以外的新增内容，不得将其自动带入迁移分支。

## Task 1: 准备测试依赖并固定解释器

**Files:**

- Read: `docs/environment/SETUP.md`
- Read: `pyproject.toml`
- Read: `uv.lock`
- Test: `tests/test_mcp_server/`、`tests/test_searcher/`及其依赖导入

**Interfaces:**

- Consumes: Task 0 的固定 SHA 和外部审计目录。
- Produces: 可重复执行全量 pytest 的 Python 环境，或明确的环境阻塞报告；不在本任务宣称代码测试已通过。

- [ ] **Step 1: 检查依赖而不安装**

```powershell
$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $pythonCommand) { throw 'python.exe not found on PATH; install/use the project Python before continuing' }
$pythonPath = $pythonCommand.Source
$version = (& $pythonPath --version 2>&1).ToString()
if ($LASTEXITCODE -ne 0) { throw "cannot start Python: $pythonPath" }
if ($version -notmatch 'Python 3\.(1[1-9]|[2-9][0-9])') { throw "Python 3.11+ required, got: $version" }
@("pythonPath=$pythonPath", "pythonVersion=$version") | Out-File (Join-Path $auditDir "python.txt") -Encoding utf8
& $pythonPath -c "import importlib; [importlib.import_module(m) for m in 'pytest pytest_asyncio mcp pyarrow lancedb pypdf docx openpyxl'.split()]; print('deps-ok')"
if ($LASTEXITCODE -ne 0) { throw 'required test dependency import failed' }
```

- [ ] **Step 2: 按 `docs/environment/SETUP.md` 安装缺失依赖**

优先使用项目提供的本地 wheel；只有本地 wheel 不存在时才请求网络安装。不要修改 `pyproject.toml` 或 `uv.lock` 来掩盖环境缺失。

- [ ] **Step 3: 仅确认测试环境可用**

Task 1 不运行代码测试，只确认解释器、版本和依赖已安装。完整测试基线必须放到 Task 2 创建的干净 `origin/main` worktree 中，并在任何 cherry-pick 之前运行。后续每个独立 PowerShell 会话都必须从 `$auditDir/python.txt` 读取同一个 `$pythonPath`，并在 Python 命令后检查 `$LASTEXITCODE`。

跨 PowerShell 会话时，先把 Task 0 输出的临时目录路径赋给 `$auditDir`，再执行：

```powershell
$pythonPath = ((Get-Content (Join-Path $auditDir 'python.txt') | Where-Object { $_ -like 'pythonPath=*' }) -split '=', 2)[1]
if (-not (Test-Path $pythonPath)) { throw "recorded Python not found: $pythonPath" }
```

- [ ] **Step 4: 放行判断**

依赖无法安装时保留失败输出并停止，不把“局部测试通过”写成全量通过。

## Task 2: 创建干净集成分支

**Files:**

- Git only: worktree/branch metadata
- Read: 当前功能分支和 `origin/main`

**Interfaces:**

- Consumes: `origin/main` 最新 SHA、Task 0 的脏工作区清单。
- Produces: `codex/merge-book-series-into-main`，起点严格为最新 `origin/main`。

- [ ] **Step 1: 不改动现有脏工作区，创建独立 worktree**

```powershell
if (Test-Path ..\llm-wiki-main-integration) { throw 'integration worktree path already exists' }
if (git branch --list codex/merge-book-series-into-main) { throw 'integration branch already exists' }
$remoteBranch = git ls-remote --exit-code --heads origin codex/merge-book-series-into-main 2>$null
$remoteBranchExit = $LASTEXITCODE
if ($remoteBranchExit -eq 0) { throw 'remote integration branch already exists' }
if ($remoteBranchExit -ne 2) { throw 'cannot verify remote integration branch; stop' }
if ((git rev-parse origin/main).Trim() -ne $baseSha) { throw 'origin/main moved before worktree creation; re-freeze Task 0' }
git worktree add --detach ..\llm-wiki-main-integration $baseSha
git -C ..\llm-wiki-main-integration switch -c codex/merge-book-series-into-main
```

如果 worktree 创建被 `.git` 权限阻塞，使用已验证的宿主权限执行；不要删除或重置当前工作区。

- [ ] **Step 2: 验证集成起点**

```powershell
git -C ..\llm-wiki-main-integration status --short
git -C ..\llm-wiki-main-integration rev-parse HEAD
```

期望：状态为空，HEAD 等于 Task 0 记录的 `origin/main` SHA。

- [ ] **Step 3: 固定源分支提交范围**

本次源范围固定为 Task 0 记录的本地 `sourceSha`，因此会包含冻结时功能分支上的全部提交（包括上次观测到的 `0c67af91`、`138cbb22`）。不要求先 push 功能分支；在集成 worktree 中按五个范围显式 cherry-pick。若用户决定只迁移远端功能分支，则必须重新计算范围，不得混用两个 HEAD。

- [ ] **Step 4: 在未应用功能提交的基线上运行测试**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'baseline pytest failed' }
Pop-Location
```

期望：收集成功并全部通过；该结果只代表 `origin/main` 基线。若失败，先区分环境问题和基线问题，不得继续 cherry-pick。

## 通用批次执行协议

每个批次都按以下顺序执行，不再为每个批次重复发明回滚规则：

1. 记录应用前的集成分支 HEAD，作为 checkpoint。
2. 用 `git cherry-pick <start>^..<end>` 应用完整范围。
3. 如发生冲突，只在当前冲突批次处理；解决后先 `git add`，运行受影响测试，再执行 `git cherry-pick --continue`。放弃当前批次时使用 `git cherry-pick --abort`，不使用 `reset --hard`。
4. 应用完成后记录实际生成的首尾提交 SHA、`git status --short`、`git diff --check $baseSha...HEAD` 和测试结果。
5. 批次失败时停止，不进入下一批。若必须回滚，使用记录的实际整批范围：`git revert --no-edit <oldest-picked>^..<newest-picked>`；Git 会按逆序处理范围内提交。若回滚本身冲突，停止并保留现场，不强行覆盖文件。

测试前后都记录集成 worktree 的 `git status --short`。如果测试在 worktree 内产生了未跟踪或已修改文件，先确认它们是测试产物；无法确认时停止并改用从当前 checkpoint 派生的临时验证 worktree，不使用 `git clean` 或覆盖未知文件。

## Task 3: 迁移批次 0——lineage 基础保护

**Files:**

- Source range: `2e2fcc03`
- Test: `tests/test_lineage/`、`tests/test_pipeline/`、与 lineage 直接相关的 `tests/test_services/`

**Interfaces:**

- Consumes: 干净集成分支。
- Produces: 集成分支上的第一个可回滚迁移提交。

- [ ] **Step 1: 预览变更和测试范围**

```powershell
git -C ..\llm-wiki-main-integration show --stat --oneline 2e2fcc03
```

- [ ] **Step 2: 应用批次**

```powershell
git -C ..\llm-wiki-main-integration cherry-pick 2e2fcc03
```

- [ ] **Step 3: 运行批次测试**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib tests/test_lineage tests/test_pipeline -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'batch 0 tests failed' }
Pop-Location
```

- [ ] **Step 4: 提交批次验收记录**

记录：测试总数、失败数、lineage 文件格式变化、旧数据读取结果、应用前 checkpoint、实际 picked 首尾 SHA 和整批回滚命令。

## Task 4: 迁移批次 1——Book 基础链路与 Web 阅读页

**Files:**

- Source range: `607c05f5..048b9883`
- Test: `tests/test_kc/` 中 Book 基础测试、`tests/test_cli_ext/`、相关 Web/API 测试
- Docs: `docs/webui-buttons.md`、Book CLI 文档

**Interfaces:**

- Consumes: 批次 0 的 lineage 接口。
- Produces: Book 基础编译、读取和 Provider 配置能力。

- [ ] **Step 1: 先检查批次是否依赖当前分支外的文件**

```powershell
git diff --name-status 607c05f5^ 048b9883
git log --reverse --format='%H %s' 607c05f5^..048b9883
```

发现依赖缺失时，暂停并将缺失提交前移到独立前置批次，不在冲突状态下继续。

- [ ] **Step 2: 应用并解决冲突**

```powershell
git -C ..\llm-wiki-main-integration cherry-pick 607c05f5^..048b9883
```

冲突只允许按当前 `main` 文件和原提交意图解决；每次解决后运行最小受影响测试，再 `git cherry-pick --continue`。

- [ ] **Step 3: 验证基础 Book/API/Web 能力**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib tests/test_kc tests/test_cli_ext tests/test_services tests/test_server -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'batch 1 tests failed' }
Pop-Location
```

- [ ] **Step 4: 验收与回滚**

必须确认 Book 读取 API、Provider 配置、Web 按钮/API 映射和现有 Wiki 摄取没有回归。失败时按通用批次协议整体回滚；如需要新增修复，单独形成明确提交后重新验证，不把未提交补丁留在集成分支。

## Task 5: 迁移批次 2——release 与书系基础契约

**Files:**

- Source range: `275304aa..919d8440`
- Test: Book release、outline、series schema、CLI gate 相关测试
- Docs: 书系方案、样例和验收文档

**Interfaces:**

- Consumes: 批次 1 的 Book 基础接口。
- Produces: 稳定 release、书系数据契约和基础 gate。

- [ ] **Step 1: 应用批次**

```powershell
git -C ..\llm-wiki-main-integration cherry-pick 275304aa^..919d8440
```

- [ ] **Step 2: 运行契约与 gate 测试**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib tests/test_kc tests/test_cli_ext tests/test_scripts -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'batch 2 tests failed' }
Pop-Location
```

- [ ] **Step 3: 验证旧数据兼容**

验证空 outline、匿名旧版 release、可选 manifest 字段、release/CURRENT 一致性；任何旧数据读取失败都阻止进入批次 3。

- [ ] **Step 4: 记录迁移回滚点**

记录本批次合并提交 SHA和可逆操作；不得用新 schema 覆盖旧 fixture 来消除失败。

## Task 6: 迁移批次 3——书系编译、lineage 和幂等

**Files:**

- Source range: `fdd5722d..d06e906f`
- Test: `tests/test_kc/`、`tests/test_lineage/`、`tests/test_pipeline/`
- Runtime data: 仅使用临时项目目录，不使用真实知识库做写入验收

**Interfaces:**

- Consumes: 批次 2 的 release/series 契约。
- Produces: 跨书来源、唯一页面归属、依赖环保护和发布幂等。

- [ ] **Step 1: 应用批次**

```powershell
git -C ..\llm-wiki-main-integration cherry-pick fdd5722d^..d06e906f
```

- [ ] **Step 2: 运行核心回归**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib tests/test_kc tests/test_lineage tests/test_pipeline tests/test_server -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'batch 3 tests failed' }
Pop-Location
```

- [ ] **Step 3: 做一次临时项目 dry-run**

必须验证：同一输入重复构建不产生重复 release；依赖环能终止；页面只归属一个章节；跨书来源和 lineage 仍闭合；失败 release 不更新 `CURRENT`。

- [ ] **Step 4: 放行门**

Book 代码链路、规则版 dry-run 和失败不更新 `CURRENT` 必须通过。真实 Provider 可读性或人工验收不属于本次代码 PR 的硬门；若未完成，只记录为“内容发布未放行”，不得把规则版 fallback 伪装成完整 LLM 发布结果。

## Task 7: 迁移批次 4——V4 摄取与提示词注入整改

**Files:**

- Source range: `a85886cc..$sourceSha`（上次观测终点为 `138cbb22`）
- Key commits: `25241d64`、`5345fc93`
- Key source: `src/pipeline/analyzer.py`、`src/pipeline/generator.py`、`src/pipeline/ingest.py`、`src/quality/quarantine.py`、`src/wiki/storage/page_writer.py`
- Test: `tests/test_pipeline/`、`tests/test_wiki/`、`tests/test_quality/`、`tests/test_queue/`

**Interfaces:**

- Consumes: 批次 3 的 Wiki/lineage/Book 结构。
- Produces: system/user 提示词边界、路径校验、候选隔离、不可重试拒绝。

- [ ] **Step 1: 应用批次并核对两个安全提交是否已包含**

```powershell
git -C ..\llm-wiki-main-integration cherry-pick a85886cc^..$sourceSha
git -C ..\llm-wiki-main-integration log --oneline -- src/pipeline/prompt_policy.py src/wiki/storage/page_writer.py
```

- [ ] **Step 2: 增加并提交页面元数据归属修复**

当前 Generator 在 candidate 路径的约 1095 行仍读取模型返回的 `type`；模型返回的 `id` 也不能成为最终 slug 的唯一来源。此修复属于本次集成的明确 Batch 4.1，不得以“临时改动”留在工作区：

1. 先写失败测试：模型返回错误 `type`、恶意 `id`/slug 或越界路径时，最终 PageType、custom type、slug 和写入目录仍由已验证的 Candidate/Analyzer 元数据及应用规则决定。
2. 实现最小修复：模型只负责 body/slot 内容；PageType、custom type、title、slug、path 和 provenance 由应用侧确定并在 Writer 前再次校验。
3. 增加 custom type 路由与 round-trip 断言：同一 `(base_type, custom_type)` 必须由统一 allowlist 路由函数决定目录，frontmatter、index 和 lineage 不能丢失 `custom_type`。
4. 为 CandidatePromoter 增加中途写失败演练：未形成完整 manifest 时不得被后续流程识别为可发布 bundle。
5. 增加一条端到端恶意模型输出测试：Candidate 固定为 `concept/title=X/custom_type=Y`，模型返回 `source/title=../../x` 时必须 quarantine/reject，且 wiki、index、vector 均无发布记录。
6. 运行 `tests/test_pipeline/`、`tests/test_wiki/`、`tests/test_quality/`、`tests/test_kc/` 中受影响测试。
7. 创建独立提交，例如 `fix(pipeline): enforce application-owned ingest metadata`，记录新 SHA，并把它列入最终 `range-diff` 的预期差异。

- [ ] **Step 3: 运行摄取安全回归**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib tests/test_pipeline tests/test_wiki tests/test_quality tests/test_queue tests/test_server tests/test_e2e -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'batch 4 security tests failed' }
Pop-Location
```

必须覆盖：system/user 分离、重试不变权、路径穿越、非法 slug、证据拒绝、quarantine、`[no-retry]`、原子写入。

Batch 4.1 最低验收矩阵：

| 反例 | 必须证明 | 失败处理 |
|---|---|---|
| 模型返回错误 `type/title/grade` | 最终页面元数据仍来自 Candidate/应用策略 | quarantine，禁止写入 |
| 模型返回恶意 `id/slug` 或越界路径 | slug、目录、index、lineage 均在项目允许范围内 | reject/quarantine，禁止写 wiki、index、vector |
| 合法 `custom_type` | frontmatter、目录、index、lineage round-trip 一致 | 阻止发布，不接受静默降级到基础类型目录 |
| CandidatePromoter 中途写失败 | 没有完整 manifest 的 bundle 不可被识别为可发布 | 保留失败证据，旧发布指针不变 |
| 无效证据或不可重试输入 | 进入 quarantine，队列标记 `[no-retry]`/dead-letter | 不重复调用模型，不写正式页面 |

- [ ] **Step 4: 做最小端到端摄取演练**

使用临时项目和恶意文本 fixture，确认原文中出现“忽略系统规则”等词不会被关键词过滤；确认模型输出不能写入 `.index`、项目外目录或额外工具路径；确认拒绝结果只出现在 quarantine。

- [ ] **Step 5: 运行 Book 与全量回归**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'final pytest failed' }
Pop-Location
```

全量测试、页面类型测试和安全端到端演练全部通过后，才允许进入最终合并门。

## Task 8: 最终合并门与 PR

**Files:**

- Git only: 集成分支与远端 PR
- Read: `.superpowers/sdd/progress.md`、全部批次验收记录、集成 worktree 中的 `git diff $baseSha...HEAD`

**Interfaces:**

- Consumes: 五个批次、Batch 4.1 修复提交和验证证据。
- Produces: 一个可审查 PR，目标为远端 `origin/main`；不直接在当前脏工作区操作。

- [ ] **Step 1: 检查集成分支干净**

```powershell
git -C ..\llm-wiki-main-integration status --short
git -C ..\llm-wiki-main-integration diff --check $baseSha...HEAD
git -C ..\llm-wiki-main-integration log --oneline $baseSha..HEAD
$integrationSha = (git -C ..\llm-wiki-main-integration rev-parse HEAD).Trim()
git range-diff "$baseSha..$sourceSha" "$baseSha..$integrationSha"
git -C ..\llm-wiki-main-integration diff --name-only $baseSha...HEAD | rg '(^|/)(raw|knowledge|\.index|\.git|secrets?|credentials?)(/|$)|(^|/)\.env($|\.)|\.(pem|key|p12|pfx)$'
```

期望：没有未提交文件；`diff --check` 无新增问题；`range-diff` 只允许显示已记录的冲突解决差异和 Batch 4.1 修复；受保护路径命令无输出。命令中的第二个 HEAD 必须使用集成 worktree 的实际 HEAD，不能使用当前脏工作区 HEAD。

- [ ] **Step 2: 运行最终检查**

```powershell
Push-Location ..\llm-wiki-main-integration
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'post-merge smoke pytest failed' }
Pop-Location

# graphify 不在集成 worktree 中运行，避免生成物污染待合并分支。
# 若需要更新图谱，在合并完成后单独对 main 的干净 checkout 执行；失败不影响代码合并。
```

graphify 不属于代码合并硬门，也不应在本任务中写入集成 worktree。若合并后需要更新图谱，先按当前 CLI 的 `graphify --help` 确认语法，再在独立干净 checkout 中执行 `graphify <path> --update`；若当前机器仍无法启动，只记录环境故障，不得生成旧图谱冒充成功，也不得因此把已经通过的代码测试判为失败。

- [ ] **Step 3: 发起 PR，不直接覆盖 main**

提交 PR 前重新检查远端目标是否移动：

```powershell
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed; do not compare stale origin/main' }
$latestMain = (git rev-parse origin/main).Trim()
if ($latestMain -ne $baseSha) { throw "origin/main moved; rebuild integration worktree from the new base" }
```

若检查失败，停止当前流程，从新的 `origin/main` 重新创建集成 worktree 并重放五个批次；不在旧集成分支上继续。

PR 创建后到真正点击合并之间，必须再执行一次同样的 `git fetch origin main` 和 SHA 比较；如果 `origin/main` 已前进，禁止直接合并，先按新基线重新验证，或启用 GitHub 的“分支过期必须更新”保护。

在用户明确授权 push 后执行：

```powershell
git -C ..\llm-wiki-main-integration push -u origin codex/merge-book-series-into-main
```

然后在 GitHub UI 创建 PR，base 选择 `main`，head 选择 `codex/merge-book-series-into-main`。个人项目默认使用 squash merge，便于 main 上一次回滚；如需保留每个 cherry-pick 提交，再选择普通 merge。无论哪种方式，都必须等检查通过后由用户明确执行合并。如果使用 `gh`，必须把下列验收内容完整写入 PR 描述，不允许空描述创建 PR。PR 必须包含：

- 批次列表和每批提交范围；
- 完整测试命令和通过数量；
- 真实 Provider/人工验收结论；该项作为内容发布状态单独记录，不把未执行的真实生成写成已通过；
- 数据迁移和回滚方法；
- 已知风险：旧数据兼容、Provider 行为、Wiki 覆盖、Book 发布状态；
- 明确说明当前分支不包含工作区未提交内容，并附 Task 0 的外部清单位置；
- Batch 4.1 页面元数据修复的提交 SHA、测试和 range-diff 结果；
- 如远端仓库有 CI，附 CI 状态；没有 CI 时明确写明“无远端 CI”。

- [ ] **Step 4: 合并后验证**

合并到远端 `origin/main` 后，新建独立 smoke-test worktree；不得在当前脏工作区执行 `git switch`：

```powershell
if (Test-Path ..\llm-wiki-main-smoke) { throw 'smoke worktree path already exists' }
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'git fetch failed; post-merge smoke test cannot use a verified main' }
git worktree add --detach ..\llm-wiki-main-smoke origin/main
if ((git -C ..\llm-wiki-main-smoke status --porcelain).Trim()) { throw 'smoke worktree is not clean' }
if ((git -C ..\llm-wiki-main-smoke rev-parse HEAD).Trim() -ne (git rev-parse origin/main).Trim()) { throw 'smoke worktree is not at fetched origin/main' }
Push-Location ..\llm-wiki-main-smoke
$env:PYTHONPATH='.'
& $pythonPath -m pytest --import-mode=importlib -q --basetemp (Join-Path ([System.IO.Path]::GetTempPath()) ("llm-wiki-pytest-" + [guid]::NewGuid().ToString("N")))
if ($LASTEXITCODE -ne 0) { throw 'post-merge smoke pytest failed' }
Pop-Location
```

随后使用临时项目目录启动 `python -m src.cli serve --host 127.0.0.1 --port <free-port>`，轮询 `/health` 直到成功或超时；执行一次 HTTP 摄取并等待任务完成，断言生成页面或 quarantine 结果符合预期，最后执行 Book dry-run 并断言不会产生空发布。服务器必须在 `try/finally` 中退出，超时、非零退出码、健康检查失败或产物断言失败均阻止验收。确认 `main` 中存在 `prompt_policy.py`、quarantine 和路径保护。

## 失败处理与回滚

- cherry-pick 冲突：停止、保留冲突现场；解决后 `git add`、运行最小测试、`git cherry-pick --continue`。放弃时使用 `git cherry-pick --abort`，不使用 `reset --hard`。
- 测试失败：只修复当前批次；若修复会改变下一批次接口，回到批次边界重新设计，不跨批次偷偷补丁。
- 数据迁移失败：在临时项目重现；真实项目只允许备份后执行，禁止把失败输出写入正式 `CURRENT`。
- 发布失败：保留旧 `CURRENT`，回滚对应批次的实际 picked SHA 范围；不删除旧 release。
- 合并前失败：在集成分支按批次实际 picked SHA 范围执行 `git revert`，或在尚未提交的当前 cherry-pick 中使用 `git cherry-pick --abort`。
- squash 合并后失败：使用 PR 生成的 squash commit 作为一个整体执行 `git revert <squash-commit>`；不能在 `main` 上引用合并前集成分支的 picked SHA 作为批次回滚依据。若采用普通 merge，才可按 main 中保留的批次提交范围回滚。
- 发现批次范围混入无关改动：停止 cherry-pick，重新从最新 `origin/main` 建立集成 worktree。
- 若 `origin/main` 在迁移期间前进：停止 PR，重新冻结新 SHA，并从新基线重放全部批次；不得把旧集成分支直接合入新 main。
- 回滚使用通用批次协议记录的整批 `git revert` 反向提交；不重写共享分支历史。

## 最终放行标准

只有同时满足以下条件，才允许合并 `main`：

1. 所有计划批次都已从最终冻结的最新 `origin/main` 重新验证，且没有未解决的 cherry-pick 冲突。
2. 集成分支干净；本地未 push 提交和工作区未提交文件已明确处理，未纳入项有外部清单。
3. 全量测试依赖可用，pytest 收集成功，全部测试通过。
4. 本次摄取安全整改的页面元数据归属缺口已关闭；模型不能决定最终 PageType、custom type、slug 或路径；Batch 4.1 修复已提交。
5. Book 代码链路和 dry-run 通过；真实 Provider/人工可读性属于内容发布门，不通过时禁止宣称完整 LLM 版本已发布，但不阻塞纯代码 PR。
6. Wiki 摄取恶意文本、路径穿越、无效证据、超时/格式失败和写入异常均有可重复测试。
7. quarantine、`[no-retry]`、AtomicContext、lineage 和 vector pending 均未回归。
8. `range-diff`、受保护路径审计和 `diff --check` 通过；graphify 若不可用只记录环境故障，不阻塞代码合并。
9. PR 中包含批次、测试、风险和回滚证据；合并前再次确认 `origin/main` 未变化；合并后在独立干净 smoke worktree 再跑一次最小测试。

当前结论：先不要合并。优先完成 Task 0–2，之后从批次 0 开始逐批验证；默认最后只创建一个 PR。若只希望尽快让摄取安全整改进入 `main`，应另建小 PR，仅迁移 `25241d64`、`5345fc93` 及 Batch 4.1 页面元数据补丁，不要等待整个 Book 功能分支。

## 方案自审

- **范围覆盖：** 覆盖 Task 0 实时冻结的全部提交（上次观测为 63 个）、当前本地未 push 提交、脏工作区、缺失测试依赖、Book 代码与内容发布的分离验收、摄取安全缺口和 graphify 环境问题。
- **最小化：** 不引入新的迁移框架、数据库或自动恢复系统；只使用 worktree、cherry-pick、pytest 和现有项目门禁。
- **可恢复性：** 合并前每个批次记录 checkpoint 和实际 picked SHA，按整批范围 revert；squash 合并后按 PR 产生的单个提交整体 revert；不重写 main 历史。
- **未来扩展：** 批次边界按稳定接口而不是临时目录切分；后续可将任一批次拆成独立 PR，不锁死 Book 或摄取演进。
- **已知限制：** 依赖安装、真实 Provider 内容验收、graphify 工具修复和远端 PR 审批仍需在执行阶段完成；这些状态不能在计划阶段虚报为已通过。Graphify 更新不属于本次代码 PR 的必要步骤。
