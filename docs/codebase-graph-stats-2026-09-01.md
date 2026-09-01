# ruflo-kb 代码知识图谱统计报告

- **生成时间**：2026-09-01
- **索引目标**：`D:\5-Project\2026814\llm-wiki-base.bak.20260822`
- **索引工具**：codebase-memory-MCP（`index_repository`，`mode=full`）
- **图谱项目名**：`llm-wiki-base`
- **索引状态**：`indexed`（`skipped_count: 0`，排除目录 160 个）

---

## 一、总量

| 指标 | 数值 |
|---|---:|
| **总节点数 (nodes)** | **39,416** |
| **总边数 (edges)** | **105,838** |
| 期望节点数 (`expected_nodes`) | 39,416 ✅ 一致 |
| 期望边数 (`expected_edges`) | 105,838 ✅ 一致 |
| 跳过文件数 | 0 |
| 排除目录数 | 160 |
| 平均出度（边/节点） | 2.69 |

> 排除目录包含 `.git`、`.venv`、`.workbuddy`、`.memory`、`.pytest_cache`、`graphify-out`、`__pycache__` 等。

---

## 二、节点标签分布（11 类，合计 39,416 ✅）

| 标签 | 数量 | 占比 | 说明 |
|---|---:|---:|---|
| Section | 19,986 | 50.7% | Markdown 章节 / 代码块切片 |
| File | 4,954 | 12.6% | 文件实体 |
| Module | 4,943 | 12.5% | **覆盖所有文件**（含 3,907 个 .md），非 Python 专属 |
| Function | 4,407 | 11.2% | 函数 |
| Method | 2,180 | 5.5% | 类方法 |
| Variable | 1,629 | 4.1% | 变量 |
| Class | 879 | 2.2% | 类 |
| Folder | 275 | 0.7% | 目录 |
| Route | 145 | 0.4% | HTTP 路由 |
| Decorator | 16 | 0.04% | 装饰器（如 `@dataclass`） |
| Branch | 1 | 0.003% | 分支节点（近乎未启用） |
| Project | 1 | 0.003% | 项目根节点 |

**关键观察**：Section 占一半以上节点，说明本仓库是「文档密集型」——`knowledge/` 下 3,616 个 Markdown 被切成 19,986 个章节节点。这是 ruflo-kb 作为知识库平台的自然结果，但会显著稀释代码信号的密度。

---

## 三、边类型分布（20 类，合计 105,838 ✅）

### 3.1 结构型边

| 类型 | 数量 | 语义 |
|---|---:|---|
| DEFINES | 45,270 | File → 符号（定义关系） |
| CONTAINS_FILE | 4,954 | Folder → File |
| DEFINES_METHOD | 2,175 | Class → Method |
| CONTAINS_FOLDER | 267 | Folder → Folder |
| HAS_BRANCH | 1 | Function → Branch |

### 3.2 依赖型边

| 类型 | 数量 | 语义 |
|---|---:|---|
| USAGE | 19,392 | 符号引用 |
| CALLS | 15,993 | 函数调用 |
| TESTS | 7,520 | 测试函数 → 被测符号 |
| WRITES | 5,083 | 变量/属性写入 |
| IMPORTS | 3,210 | 模块导入 |
| DECORATES | 819 | 类/函数 → 装饰器 |
| CONFIGURES | 260 | 配置引用 |
| INHERITS | 72 | 类继承 |

### 3.3 语义 / 相似型边（full 模式特有）

| 类型 | 数量 | 语义 |
|---|---:|---|
| SIMILAR_TO | 247 | 代码相似（克隆候选） |
| SEMANTICALLY_RELATED | 151 | 语义相关 |
| FILE_CHANGES_WITH | 143 | 文件协同变更（耦合信号） |
| HANDLES | 128 | Function → Route |
| HTTP_CALLS | 74 | 前端 → Route |
| RAISES | 62 | 抛出异常 |
| THROWS | 17 | JS throw |

---

## 四、文件维度（File 节点 4,954）

### 4.1 按扩展名

| 扩展名 | 数量 | | 扩展名 | 数量 |
|---|---:|---|---|---:|
| `.md` | 3,907 | | `.toml` | 1 |
| `.py` | 947 | | `.html` | 1 |
| `.yaml` | 44 | | `.css` | 1 |
| `.json` | 26 | | `.cjs` | 1 |
| `.js` | 15 | | `.csv` | 1 |
| `.sh` / `.bat` / `.yml` | 4 / 2 / 2 | | `.gitattributes` | 2 |

**代码文件仅 947 个（19.1%），Markdown 占 78.9%。**

### 4.2 文件数最多的目录（Top 15）

| 目录 | 文件数 |
|---|---:|
| `knowledge/novel-wiki/wiki/concepts` | 924 |
| `knowledge/novel-wiki/wiki/sources` | 485 |
| `knowledge/novel-wiki/raw/sources/04_题材专题` | 405 |
| `knowledge/novel-wiki/raw/sources/02_进阶技巧` | 380 |
| `knowledge/novel-wiki/raw/sources/01_新手入门` | 355 |
| `knowledge/novel-wiki/wiki/entities` | 323 |
| `knowledge/_batch50-20260815/wiki/entities` | 169 |
| `knowledge/_batch50-20260815/wiki/concepts` | 130 |
| `tests/test_kc` | 73 |
| `knowledge/novel-wiki/raw/sources/03_大纲创作` | 71 |
| `scripts` | 63 |
| `tests/test_pipeline` | 60 |
| `tests/test_wiki` | 56 |
| `knowledge/novel-wiki/raw/sources/05_运营出版` | 56 |
| `src/pipeline` | 33 |

---

## 五、模块 / 包依赖关系

### 5.1 建模事实（重要）

- `Module` 标签**覆盖全部 4,943 个文件**，包括 3,907 个 `.md` —— 它不是 Python 模块的同义词。
- `IMPORTS` 边的两端**都不是** `Module` → `Module`。实际形态是：

  **`File`（导入方模块）—IMPORTS→ `目标符号`**

  目标符号分布：

  | 目标标签 | 数量 | 占比 |
  |---|---:|---:|
  | Module | 1,816 | 56.6% |
  | Class | 574 | 17.9% |
  | Function | 510 | 15.9% |
  | Folder | 234 | 7.3% |
  | Variable | 62 | 1.9% |
  | Method | 14 | 0.4% |

> ⚠️ 因此 `(a:Module)-[:IMPORTS]->(b:Module)` 这类直觉查询**永远返回 0**。正确写法是 `MATCH (a:File)-[:IMPORTS]->(b:Module)`。

### 5.2 被依赖最多的模块（入度 Top 15）

| 模块 | 被导入次数 |
|---|---:|
| `src.wiki.core.types` | 142 |
| `src.knowledge.core.object` | 116 |
| `src.wiki.core.paths` | 100 |
| `src.wiki.storage.page_writer` | 60 |
| `src.wiki.storage.ensure` | 59 |
| `src.types` | 38 |
| `src.wiki.features.metrics` | 36 |
| `src.kc.integrity.gates` | 34 |
| `src.orchestrator.batch_runner` | 33 |
| `src.pipeline.extraction_types` | 26 |
| `src.lib.atomic_ctx` | 24 |
| `src.services.batch_state` | 24 |
| `src.permissions` | 23 |
| `src.lib.write_hooks` | 23 |
| `src.llm.types` | 22 |

> 去重后共 **272 个被导入模块**，累计 1,816 条模块级导入边。

### 5.3 依赖他人最多的文件（出度 Top 15）

| 导入方 | 导入数 |
|---|---:|
| `src.cli.__file__` | 80 |
| `src.kc.views.book.__file__` | 47 |
| `src.pipeline.ingest.__file__` | 30 |
| `src.wiki.__file__` | 26 |
| `src.pipeline.generator.__file__` | 25 |
| `tests.test_kc.test_integrity_idempotency_e2e.__file__` | 23 |
| `src.queue.service.__file__` | 22 |
| `src.pipeline.text_preprocessing.__file__` | 21 |
| `scripts.batch_executor.__file__` | 21 |
| `web.__file__` | 16 |

> `src/cli.py` 以 80 个导入高居榜首，是全仓最大的扇出点（CLI 聚合了所有子命令）。

### 5.4 包级依赖（2 级包）

**入度（被依赖最多）—— 谁是地基**

| 包 | 入度 |
|---|---:|
| `src.wiki` | 549 |
| `src.knowledge` | 250 |
| `src.kc` | 226 |
| `src.pipeline` | 132 |
| `src.llm` | 77 |
| `src.lib` | 57 |
| `src.utils` | 41 |
| `src.services` | 40 |
| `src.orchestrator` / `src.cli_ext` | 39 / 39 |
| `src.types` | 38 |
| `src.schemas` | 33 |
| `src.searcher` | 29 |
| `src.project` / `src.agent` | 24 / 24 |
| `src.permissions` | 23 |

**出度（依赖他人最多）—— 谁最"玻璃"**

| 包 | 出度 |
|---|---:|
| `tests.test_wiki` | 288 |
| `tests.test_kc` | 233 |
| `tests.test_pipeline` | 225 |
| `tests.test_knowledge` | 100 |
| `tests.test_cli_ext` | 82 |
| `src.kc` | 72 |
| `src.knowledge` | 71 |
| `tests.test_queue` | 58 |
| `tests.test_llm` | 53 |
| `src.pipeline` | 42 |

> 出度榜几乎被测试包占据 —— 测试是最大的依赖消费者，占比远超生产代码。

### 5.5 src 内部（生产代码）依赖矩阵

仅统计 `src.* → src.*` 的 **232 条**边（仅占全部 1,816 条的 12.8%）。行 = 依赖方（out），列 = 被依赖方（in）：

```
out\in         knowledge   kc  pipeline  wiki  agent  services  server  orchestrator  utils  cli_ext  lib  searcher  events
knowledge            51     4       .      5      .       .        .         .          .       .      4       4       2
kc                   13    55       .      2      .       .        .         .          1       .      .       .       .
pipeline              9     5      18      2      .       .        .         .          5       .      .       .       .
wiki                  .     .       .      4      .       .        .         .          .       .      .       .       .
agent                 8     .       1      7      .       .        .         .          .       .      .       2       1
server                .     1       .      .      .      10        .         .          .       .      .       .       .
orchestrator          .     .       .      3      .       3        .         .          .       .      1       .       .
cli_ext               .     .       .      .      .       .        .         4          .       .      .       .       .
```

**不稳定性指标 I = out / (in + out)**（0 = 纯粹被依赖/稳定，1 = 纯粹依赖他人/易变）：

| 子包 | I | out | in | 解读 |
|---|---:|---:|---:|---|
| `agent` | 1.00 | 20 | 0 | 纯消费方，无人依赖 |
| `server` | 1.00 | 11 | 0 | 纯消费方（HTTP 层，合理） |
| `cli` | 1.00 | 1 | 0 | 纯消费方 |
| `cli_ext` | 0.80 | 4 | 1 | 偏消费 |
| `pipeline` | 0.69 | 42 | 19 | 偏消费 |
| `orchestrator` | 0.64 | 7 | 4 | 偏消费 |
| `kc` | 0.53 | 72 | 65 | 双向耦合最重的包 |
| `knowledge` | 0.47 | 71 | 81 | 接近平衡，核心域 |
| `wiki` | **0.15** | 4 | 23 | **最稳定，事实上的地基** |
| `services` / `utils` / `lib` / `searcher` / `events` | 0.00 | 0 | 13/6/5/4/4 | 纯被依赖的叶子设施 |

> **结论**：`src.wiki` 是架构地基（I=0.15），`src.knowledge` 与 `src.kc` 是耦合最重的双核（互相导入 13 / 4 条），`src.kc` 内部自依赖 55 条（占其出度 76%），内聚性高。

### 5.6 外部 → src 的依赖（1,539 条）

| 目标子包 | 外部依赖数 | | 目标子包 | 外部依赖数 |
|---|---:|---|---|---:|
| `wiki` | 526 | | `queue` | 21 |
| `knowledge` | 169 | | `collector` | 20 |
| `kc` | 161 | | `maintenance` | 17 |
| `pipeline` | 113 | | `events` / `vector` | 15 / 15 |
| `llm` | 76 | | `server` | 14 |
| `lib` | 52 | | `quality` | 11 |
| `cli_ext` | 38 | | `vision` / `circuit_breaker` | 9 / 9 |
| `types` | 36 | | `metrics` | 5 |
| `utils` | 35 | | `mcp_server` / `templates` | 3 / 3 |
| `orchestrator` | 35 | | `sync` | 2 |
| `schemas` | 33 | | | |
| `services` | 27 | | | |
| `searcher` | 25 | | | |
| `agent` / `project` | 24 / 24 | | | |
| `permissions` | 21 | | | |

### 5.7 循环依赖检测

对模块级导入图做 Tarjan 强连通分量分析：

| 范围 | 节点 | 边 | 循环分量 |
|---|---:|---:|---:|
| 全量（含 tests/scripts） | 456 | 1,078 | **0** |
| 仅 src 生产代码 | 72 | 154 | **0** |

✅ **未发现任何模块级循环依赖**，分层是干净的。

### 5.8 同包 / 跨包比例

- 同包内依赖（3 级包口径）：62 / 1,816 = **3.4%**
- 跨包依赖：**96.6%**

> 内聚度偏低、耦合面偏宽。绝大多数模块都跨包取用符号，说明 `src/` 下的子包边界更多是「目录归类」而非「封装边界」。

---

## 六、函数 / 方法依赖关系

### 6.1 规模

| 类别 | 全仓 | Python 子集（`.py`） | 占比 |
|---|---:|---:|---:|
| Function | 4,407 | **4,246** | 96.3% |
| Method | 2,180 | **2,175** | 99.8% |
| Class | 879 | **863** | 98.2% |

> 全仓与 Python 子集高度重合，说明代码图谱几乎全部来自 Python，JS（`web/`）仅贡献约 160 个函数节点。
> Python 代码总量：4,246 函数 + 2,175 方法 + 863 类 = **7,284 个可调用单元**，分布在 947 个 `.py` 文件中，平均 7.7 个/文件。

### 6.2 CALLS 边（15,993 条）端点分布

**源端（谁在调用）**

| 源标签 | 数量 | 占比 |
|---|---:|---:|
| Function | 11,008 | 68.8% |
| Method | 4,261 | 26.6% |
| Module | 398 | 2.5% |
| File | 326 | 2.0% |
| Class / Variable | 0 | 0% |

**目标端（谁被调用）**

| 目标标签 | 数量 | 占比 |
|---|---:|---:|
| Function | 7,380 | 46.1% |
| Method | 4,568 | 28.6% |
| Class | 3,863 | 24.2% |
| Route | 129 | 0.8% |
| Variable | 52 | 0.3% |
| Module | 1 | 0.01% |

**函数↔方法调用矩阵**

| 源 \ 目标 | Function | Method |
|---|---:|---:|
| Function | 5,946 | 2,398 |
| Method | 1,130 | 1,949 |

> 模块级调用（`Function→Method` 2,398 条）显著高于反向（`Method→Function` 1,130 条），说明**自由函数大量调用类方法**——即「面向过程的外层 + 面向对象的内核」结构。

### 6.3 被调用最多的函数（入度 Top 20）

| 函数 | 调用者数 |
|---|---:|
| `builtins.len` ⚠️ | 783 |
| `src.wiki.storage.ensure.ensure_knowledge_base` | 277 |
| `builtins.print` ⚠️ | 218 |
| `src.wiki.storage.page_writer.write_page` | 122 |
| `src.wiki.templates.resolver.resolve` | 81 |
| `src.wiki.storage.page_writer.read_page` | 59 |
| `src.lib.write_hooks.safe_write` | 38 |
| `src.services.search.search` | 36 |
| `src.wiki.templates.parser.parse` | 35 |
| `src.wiki.features.indexer.append_to_index` | 31 |
| `src.wiki.features.lint.lint_wiki` | 31 |
| `src.wiki.storage.page_writer.page_path_for` | 35 |
| `src.kc.compiler.normalize.normalize_text` | 28 |
| `src.kc.views.book.materialize.materialize_book_snapshot` | 26 |
| `src.knowledge.core.adapter.wiki_page_to_knowledge_object` | 25 |
| `src.kc.integrity.identity_key.compute_identity_key` | 22 |
| `src.services.batch_state.load_batch_state` | 22 |
| `src.services.batch_state.raw_status` | 22 |
| `src.wiki.features.batch_reconcile.reconcile_batch` | 22 |
| （其余为测试辅助函数 `_make_*`，各 22–40） | |

**剔除 builtins 噪声后的真正核心函数 Top 5**：

1. `ensure_knowledge_base`（277）— KB 初始化门面
2. `write_page`（122）— 唯一写入口
3. `resolve`（81）— 模板解析
4. `read_page`（59）— 页面读取
5. `safe_write`（38）— 原子写

> 这 5 个构成 ruflo-kb 的**事实 I/O 主干**：任何对它们的改动都会波及 500+ 调用点。

### 6.4 调用他人最多的函数（出度 Top 15）

| 函数 | 出度 |
|---|---:|
| `src.pipeline.ingest.generate_ingest` | 42 |
| `src.orchestrator.batch_runner.run_batch` | 30 |
| `src.pipeline.generator.unified_generate` | 24 |
| `src.pipeline.generator.generate` | 24 |
| `src.pipeline.generator.generate_from_candidate` | 22 |
| `scripts.batch_gate_v3.gate_batch` | 22 |
| `src.pipeline.generator.generate_from_knowledge_object` | 20 |
| `scripts.batch_commit._commit_one_batch` | 20 |
| `src.wiki.features.lint.lint_wiki` | 19 |
| `scripts.phase4_batch.main` | 19 |
| `scripts.audit_wiki_baseline.main` | 19 |
| `src.research.runner.run_deep_research` | 17 |
| `scripts.phase5_accept.main` | 16 |
| `scripts.audit_blindspots.main` | 16 |
| `src.kc.views.book.compiler._compile_chapter_inner` | 15 |

> `generate_ingest`（42 出度）是**全仓最复杂的编排点**——与你正在推进的 ingest interface unification 直接相关，属于高风险改动区。

### 6.5 TESTS 边（7,520 条）

- 源端：Function 5,054 / Method 2,341 / File 125
- 目标端：Function 3,044 / Class 2,220 / Method 2,180 / Route 68 / Variable 8

**测试覆盖缺口**：863 个 Python 类中仅 2,220 条 TESTS 边（含重复），4,246 个函数中仅 3,044 条。以去重口径估算，约 **40–45% 的被测符号有测试指向**。

---

## 七、复杂度热点（Python 函数）

| 指标 | 数值 |
|---|---:|
| Python 函数总数 | 4,246 |
| 圈复杂度总和 | 5,771 |
| 最大圈复杂度 | 61 |
| 最大认知复杂度 | 170 |
| 平均圈复杂度 | 1.36（大量函数为 0/未计算） |
| 复杂度 ≥ 10 的函数 | 127（3.0%） |
| 复杂度 ≥ 20 的函数 | 23（0.5%） |
| 认知复杂度 ≥ 30 | 57 |
| 循环内线性扫描（`linear_scan_in_loop ≥ 1`） | 31 |

**传递嵌套循环深度 Top 10**（`transitive_loop_depth`，跨过程传播的最坏嵌套度）：

| 函数 | TLD | 圈复杂度 | 认知复杂度 |
|---|---:|---:|---:|
| `src.orchestrator.batch_runner.run_batch` | **14** | 58 | 106 |
| `src.orchestrator.batch_runner._rerun_gate_batch` | 13 | 10 | 20 |
| `scripts.batch_build.phase_ingest` | 13 | 8 | 17 |
| `scripts.batch_build.run` | 13 | 5 | 6 |
| `scripts.batch_build.main` | 13 | 0 | 0 |
| `src.orchestrator.batch_runner._generate_raw` | 12 | 0 | 0 |
| `src.wiki.features.lint.lint_wiki` | 5 | 45 | **163** |
| `src.pipeline.analyzer.analyze` | 4 | 15 | 40 |
| `src.pipeline.analyzer._analyze_json` | 3 | 15 | 40 |
| `src.kc.views.book.compiler._compile_chapter_inner` | 3 | 11 | 20 |

> **头号热点**：`run_batch` 传递嵌套深度 14、圈复杂度 58、认知复杂度 106、出度 30 —— 同时是调用热点和复杂度热点，是全仓风险最集中的单点。
> **二号热点**：`lint_wiki` 认知复杂度 163（全仓最高）且含循环内线性扫描，出度 19、入度 31 —— 典型的"人人依赖 + 又慢又复杂"。

---

## 八、其他结构信号

- **继承**：`Class -INHERITS-> Class` 72 条（863 个 Python 类中仅 8.3% 参与继承，偏扁平，倾向组合/数据类）
- **装饰器**：819 条，形态为 `Class/Function -DECORATES-> Decorator`（方向与你直觉相反）。16 个 Decorator 节点，主体是 `@dataclass`
- **路由**：145 个 Route 节点；`Function -HANDLES-> Route` 118 条边（覆盖 **60** 个去重路由），`* -HTTP_CALLS-> Route` 74 条边（覆盖 **53** 个去重路由）。
  - ⚠️ 118 + 74 = 192 > 145，存在多处理器挂同一路由 / 命名规范不一致（后端 `GET /projects/{}` vs 前端 `ANY /api/v1/projects/{}.state.projectId/...`）。
  - 经本地规范化比对（去 `/api/v1` 前缀、折叠 `{}` 插值残片）两组落盘边集后：
    - **后端↔前端双向匹配** 25 条（实现 + 调用齐全，健康）
    - **仅后端实现、前端零调用** 26 条（如 `/health`、`/ready`、`/projects/{}/collect`、`/book/build`、`/compile`、`/projects/{}/templates/*`、`/projects/{}/heat/*`、`/projects/{}/pages/{}/verify`）——属 UI 未接入或仅 CLI/测试调用，是"可审计但未死"的候选
    - **前端调用但后端无匹配实现** 24 条，其中约 20 条是测试夹具文件路径噪声（`/tmp/*.md`、`/docs/*.pdf`、`/home/user/*`），真实缺口仅 ~4 条：`/kc/book/build`、`/kc/book/status`、`/projects/{}/ingest/batch`、`/scenario-templates`（可能为命名不一致或尚未落地端点）
  - 另有约 **57** 个 Route 节点既无 HANDLES 也无 HTTP_CALLS（疑为 `web/` 前端路由定义，未接入后端边），需单独核对。
  - ✅ **更正上一轮推断**：不存在"145 个里 27 个死路由"的说法；真正的「已定义但前端零调用」是 **26 条（占已处理 60 条的 43%）**，属 UI 覆盖缺口而非死代码。
- **异常**：RAISES 62 + THROWS 17 = 79
- **写入**：WRITES 5,083 条 → Variable 3,772 / Function 659 / Method 624 / Class 28
- **相似代码**：SIMILAR_TO 247 对（克隆候选），SEMANTICALLY_RELATED 151 对
- **协同变更**：FILE_CHANGES_WITH 143 对（隐式耦合信号，值得做一次定向审查）
- **CONFIGURES**：260 条

---

## 九、数据质量提示（读图时务必注意）

1. **builtins 污染**：`builtins.str` / `builtins.int` / `builtins.list` / `builtins.dict` / `builtins.range` 各有 938 条 DEFINES 边，`builtins.len` 783 条、`builtins.print` 218 条 CALLS 边。
   - 影响：`DEFINES→Class` 名义 5,564 条，**去重后真实项目类仅 835 个**（874 条边）；`DEFINES→Function` 名义 6,281 条，**真实 4,025 个**（4,308 条边）；`DEFINES→Method` 名义 6,865 条，**真实 1,652 个**（2,016 条边）。
   - 规避：统计时加 `WITH b, count(*) AS n WHERE n <= 20` 过滤高频外部符号。

2. **`src/__init__.py` 与 `tests/__init__.py` 被误记为大量符号的定义者**（329 / 170 条 DEFINES）。这是索引器把包内符号归集到 `__init__` 的副作用，不是真实代码结构。

3. **`Module` 标签不等于 Python 模块**：3,907 个 `.md` 也带 Module 标签。

4. **`IMPORTS` 不是 Module→Module**：见 §5.1。

5. **Cypher 引擎限制**：不支持 `split()`；支持 `STARTS WITH`、`ENDS WITH`、`WITH ... WHERE` 后过滤、`count/sum/avg/min/max/collect/size/length/labels/keys` 等。
   - 分组聚合时**不要**用 `RETURN labels(a)[0], labels(b)[0], count(*)` —— 引擎会先物化全量分组再截断，导致响应爆炸落盘。改用 `MATCH (a:Label)-[:EDGE]->(b:Label) RETURN count(*)` 逐对探测。

---

## 十、结论摘要

| 维度 | 结论 |
|---|---|
| 图谱规模 | 39,416 节点 / 105,838 边，索引完整（expected 一致，0 跳过） |
| 仓库性质 | 文档密集型：Markdown 占 File 的 78.9%，Section 占节点的 50.7% |
| 代码规模 | 947 个 `.py` → 4,246 函数 + 2,175 方法 + 863 类 |
| 架构地基 | `src.wiki`（入度 549，不稳定性 I=0.15） |
| 耦合双核 | `src.knowledge` ↔ `src.kc`（互相依赖，I 分别 0.47 / 0.53） |
| 最大扇出 | `src/cli.py`（80 导入）、`generate_ingest`（42 调用出度） |
| 最大扇入 | `ensure_knowledge_base`（277 调用者）、`write_page`（122） |
| 复杂度单点 | `run_batch`（TLD 14 / 圈 58 / 认知 106）、`lint_wiki`（认知 163） |
| 依赖健康度 | ✅ 零循环依赖；⚠️ 跨包依赖占 96.6%，同包内聚仅 3.4% |
| 测试覆盖 | 估计 40–45%，约 115 个类/函数热点无测试指向 |
| 路由健康度 | 60 后端路由中 26 条前端零调用（UI 缺口）；~4 条前端路径后端无实现；~57 个 Route 节点未接入任何边 |
| 依赖消费方 | 包内矩阵中 `agent` / `server` / `cli` 入度为 0（纯消费方，无人依赖，改动影响面小） |

---

*本报告数据全部来自 codebase-memory-MCP 图谱查询（索引 `mode=full`，项目名 `llm-wiki-base`）。其中：包级依赖矩阵由落盘的 1,816 条模块级导入边全量解析后本地聚合得到（已校验 1816/1816 完整读取）；路由覆盖比对由落盘的 HANDLES（60 去重路由）/ HTTP_CALLS（53 去重路由）两组边集经本地规范化（去 `/api/v1`、折叠 `{}` 插值）后比对得到，无需重复查询图谱。*
