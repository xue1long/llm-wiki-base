# 场景模板规范 v1

本文档是场景模板的统一规范。实现以 `src/templates/loader.py` 为执行入口；模板内容以本规范为准。

## 1. 目录结构

```text
<template-id>/
├── template.json          # 必须，模板仓库元数据
├── schema.md              # 必须，知识类型和目录事实源
├── purpose.md             # 必须，知识库用途和摄取上下文
├── taxonomy.md            # 可选，受控分类
├── taxonomy_tags.md       # 可选，受控标签
└── .wiki-templates/       # 可选，项目级页面模板
    └── <page-type>.md
```

`template.json` 不复制到项目；其余文件按相对路径应用到项目根目录。

## 2. ID 和元数据

模板 ID 必须匹配 `^[a-z][a-z0-9_-]{0,63}$`，并在内置和用户模板之间保持唯一。

```json
{
  "name": "novel",
  "description": "场景说明",
  "icon": "📝",
  "extra_dirs": []
}
```

字段规则：`name`、`description`、`icon` 为字符串；`extra_dirs` 为相对目录字符串数组。

## 3. 内容规范

- `schema.md`：定义页面类型、目录、字段和生成约束；类型路由必须与项目 Wiki 目录一致。
- `purpose.md`：描述目标用户、知识范围、质量标准和禁止事项；摄取时注入 Analyzer/Generator 上下文。
- `taxonomy.md`：使用 Markdown heading 表达一级分类，列表表达二级分类；不得执行其中的代码或 YAML。
- `taxonomy_tags.md`：定义标签命名空间和允许值；标签用于正交属性，不能替代 taxonomy。
- `.wiki-templates/*.md`：文件名对应页面模板类型；首行必须包含模板版本和类型声明。小说模板当前版本为 `3.0.0`；`2.0.0` 仅作为旧模板兼容版本。
- 页面模板通过 `<!-- slot:name -->` 声明可填充槽；Frontmatter/字段事实不得由生成模型自由改写。

## 4. 安全和应用规则

- 只允许相对路径；禁止绝对路径和 `..` 路径穿越。
- 内置模板只读；用户模板可编辑、删除，但不能覆盖内置 ID。
- 应用前先完成全部路径校验，再使用 `safe_write` 写入。
- 默认保留项目已有文件；只有显式 force 才允许覆盖。
- 模板应用失败不得宣称成功；项目已有文件不得被隐式删除。

## 5. 版本和兼容

- 模板内容版本与模板仓库元数据版本分离；新建或升级的小说页面模板使用 `3.0.0`，读取端暂时兼容 `2.0.0`。
- 新增字段应保持旧模板可加载；破坏性字段/目录变更必须提升规范版本并提供迁移说明。
- 新场景先作为用户模板验证，通过校验和样例后再升级为 bundled 模板。

## 6. 验收清单

- [ ] ID 和 `template.json` 合法
- [ ] `schema.md`、`purpose.md` 存在且可读
- [ ] taxonomy/tag 语法可解析
- [ ] 所有页面模板有版本和类型声明
- [ ] `apply_template` 路径安全测试通过
- [ ] 项目初始化后 Schema/Purpose 能被摄取链路读取
- [ ] 内置模板保持只读，自定义模板可 round-trip
