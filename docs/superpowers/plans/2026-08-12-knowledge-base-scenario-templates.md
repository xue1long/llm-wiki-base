# 知识库场景模板与自定义模板方案

## 1. 需求描述

为知识库实例创建流程增加场景模板能力，并吸收 `D:\5- 项目\000-Nico\llm_wiki-main` 的模板模型：

- 创建知识库时可选择场景模板；
- 内置 Research、Reading、Personal Growth、Business、General 五类模板；
- 模板至少包含 `schema.md`、`purpose.md` 和可选扩展目录；
- 用户可以从现有模板复制创建新模板；
- 用户可以修改自定义模板的元数据、`schema.md`、`purpose.md`、扩展目录和页面模板；
- General 模板包含当前已有的 `source/entity/concept/synthesis` 页面模板，应用后成为该知识库的项目级页面模板副本。

## 2. 现状与约束

当前项目已有两套相关机制：

1. `src/templates/loader.py`：按目录加载项目场景文件，目前只有 research，CLI 支持 `project init --template`。
2. `src/wiki/templates/`：按 PageType 解析页面模板，优先级为项目 → 用户 → bundled。

对方项目的 TypeScript 模板数据不能直接复制，因为它依赖 React/Tauri 文件系统命令；可迁移的是场景内容、元数据和目录模型。

## 3. 领域模型

### 3.1 场景模板

`ScenarioTemplate` 表示“创建知识库时使用的一组初始文件和目录”。

字段：

- `id`：稳定标识，`[a-z0-9][a-z0-9_-]*`；内置模板和用户模板共用命名空间；
- `name`：显示名称；
- `description`：场景说明；
- `icon`：显示图标，可为空；
- `files`：模板目录内的相对文件；至少包含 `schema.md` 和 `purpose.md`；
- `extra_dirs`：创建时需要确保存在的相对目录。

`schema.md` 是类型和路由事实源；`purpose.md` 是摄取时注入 LLM 的目标和上下文；页面模板文件是项目级结构覆盖。

### 3.2 内置与自定义

- 内置模板位于 `src/templates/bundled/<id>/`，只读；
- 自定义模板位于用户配置目录 `~/.config/ruflo-kb/templates/<id>/`，可创建、编辑、删除；
- 自定义模板可以从任意可见模板复制，复制后与源模板解耦；
- 自定义模板不能覆盖内置模板同名 ID，避免修改 bundled 资源造成升级不可控。

## 4. 模块接口

新增/扩展 `src/templates` 模块，对外通过 `src/templates/__init__.py` 暴露 facade：

```python
list_templates() -> list[ScenarioTemplate]
load_template(template_id: str) -> ScenarioTemplate
create_template(template_id: str, *, source_id: str | None = None, metadata: ...) -> ScenarioTemplate
update_template(template_id: str, *, metadata: ..., files: ..., extra_dirs: ...) -> ScenarioTemplate
delete_template(template_id: str) -> None
apply_template(template_id: str, project_root: Path) -> list[Path]
```

模板目录使用 `template.json` 保存元数据；`schema.md`、`purpose.md`、`.wiki-templates/*.md` 等内容保持普通文件，复用现有递归加载和安全写入逻辑。`template.json` 只属于模板仓库元数据，不会被复制到知识库实例。

## 5. 方案结构

### 5.1 模板存储

```text
src/templates/bundled/
├── general/
│   ├── template.json
│   ├── schema.md
│   ├── purpose.md
│   └── .wiki-templates/
│       ├── source.md
│       ├── entity.md
│       ├── concept.md
│       └── synthesis.md
├── research/
├── reading/
├── personal/
└── business/

~/.config/ruflo-kb/templates/<custom-id>/
    ├── template.json
    ├── schema.md
    ├── purpose.md
    └── ...
```

### 5.2 创建知识库

CLI `project init --template <id>` 和未来 HTTP 创建接口都调用同一个 `apply_template()`：

1. 创建基础知识库目录；
2. 读取模板并校验相对路径，拒绝绝对路径和 `..` 穿越；
3. 写入模板文件；
4. 创建 `extra_dirs`；
5. 重新读取 `schema.md`，让 `SchemaRegistry` 为自定义类型准备目录。

模板应用是可校验的单次操作：所有目标路径先完成相对路径、`..`、绝对路径和目标根校验，再开始写入；写入阶段复用 `safe_write`，每个文件保持原子替换，业务校验异常时不提交缓冲写入。磁盘 flush 失败时报告具体失败路径，不宣称跨文件物理事务回滚。已有同名文件默认保留，只有显式 `--force`/覆盖选项才允许替换。

### 5.3 自定义模板

CLI 增加：

```text
templates list
templates show <id>
templates create <id> [--from <id>]
templates edit <id> [--metadata-json ...]
templates apply <id> --project <project>
templates delete <id>
```

编辑操作使用已有安全写入机制；内容编辑不引入新的编辑器依赖。模板目录本身可被用户直接编辑，CLI 负责元数据和校验。可编辑文件限制为 `template.json` 的允许字段、`schema.md`、`purpose.md`、`.wiki-templates/*.md` 及 manifest 声明的文本文件；禁止通过 API 任意写入模板根目录之外的路径。

### 5.4 WebUI / HTTP

新增场景模板 HTTP 接口，与现有项目页面模板接口区分：

- `GET /api/v1/scenario-templates`
- `GET /api/v1/scenario-templates/{id}`
- `POST /api/v1/scenario-templates`
- `PUT /api/v1/scenario-templates/{id}`
- `DELETE /api/v1/scenario-templates/{id}`

项目创建接口增加 `template` 字段；WebUI 创建知识库时显示模板卡片，模板管理页面增加场景模板编辑入口。现有页面模板编辑接口继续保持不变。

## 6. 兼容策略

- 现有 `research` 目录无 `template.json` 时按目录名和默认元数据兼容加载；
- 现有四类 PageType 模板继续由 `src/wiki/templates/bundled` 提供；General 只是在新项目中复制一份项目级覆盖；
- 旧的 `templates apply` 命令继续可用，内部改为调用统一 `apply_template()`；
- 旧项目不会自动覆盖其已有 `schema.md`、`purpose.md` 或 `.wiki-templates` 文件。
- 旧版模板目录若没有 `template.json`，继续以目录名加载，并使用默认名称、说明、空图标和从文件推导的扩展目录；升级或编辑时才补写 manifest。

## 7. 不纳入本次范围

- 不把每种自定义页面类型自动生成独立 slot 模板；没有项目级模板时继续回退基础 PageType；
- 不支持从任意外部 ZIP/URL 导入模板；
- 不修改对方项目的 TypeScript/Tauri 代码；
- 不把模板元数据写入知识库内容索引。

## 8. 验收标准

1. `templates list` 显示五个内置模板和用户自定义模板；
2. `project init --template general` 会生成 `schema.md`、`purpose.md` 和四个 `.wiki-templates/*.md`；
3. Research 等场景的自定义类型目录在创建时生成，摄取时由 `SchemaRegistry` 识别；
4. 可从 General 创建自定义模板，修改后再次创建知识库能看到修改内容；
5. 内置模板不可被覆盖或删除；
6. 模板路径穿越、重复 ID、缺少必需文件、非法元数据均有明确错误；
7. CLI、HTTP、WebUI 共享同一模板模块，不复制业务逻辑；
8. 现有模板解析、项目初始化和摄取测试不回归。

## 9. 审查补充：边界与失败策略

| 场景 | 预期行为 |
|---|---|
| 模板 ID 含路径分隔符、`..` 或非法字符 | 创建/更新前拒绝，不写磁盘 |
| 缺少 `schema.md` 或 `purpose.md` | 自定义模板创建/更新失败并指出缺失文件；旧无 manifest 模板按兼容规则读取 |
| `template.json` 损坏或字段类型错误 | `list` 跳过并报告错误，`load/apply` 返回可定位错误，不静默使用半成品 |
| 应用模板时目标文件已存在 | 默认保留并报告冲突；显式 force 才覆盖 |
| 应用过程中业务校验失败 | 不开始写入 |
| 磁盘 flush 失败 | 报告具体失败路径，单文件不产生撕裂 |
| HTTP 请求指定未知模板 | 返回 404/400，不创建项目或修改现有项目 |
| 自定义模板删除 | 仅允许删除用户模板；已创建的知识库不受影响，因为应用的是文件副本 |

## 10. 任务拆分

1. 定义模板领域类型、manifest 校验和存储 facade；
2. 迁移五个内置场景模板，General 携带四类页面模板；
3. 统一 CLI list/show/create/edit/delete/apply 与 project init；
4. 增加场景模板 HTTP API 和项目创建模板参数；
5. 增加 WebUI 模板选择与自定义模板编辑；
6. 补充单元、CLI、API、端到端创建测试和文档。
