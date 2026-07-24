# 小说创作素材库 — 初始化设计

## 目标

在 `F:\2026-7-21\knowledge\novel-wiki\` 初始化独立项目，将 `raw/sources/` 和 `Inbox/Processing/` 下的 7 份创作资料摄入，构建可检索的知识库。

## 架构

```
F:\2026-7-21\knowledge\novel-wiki\
├── wiki/
│   ├── sources/       # 原始文档
│   ├── entities/      # 实体（人物、技巧概念）
│   ├── concepts/      # 核心概念（爽点、大纲、节奏…）
│   ├── synthesis/     # 综合页面（创作指南体系）
│   ├── _stubs/       # 待填充的占位页面
│   ├── index.md      # 页面目录
│   └── log.md        # 摄入日志
├── raw/sources/      # 原始文件副本
└── .llm-wiki/        # 项目配置（ID、Schema）
```

## 摄入流程

1. `python -m src.cli project init F:\2026-7-21\knowledge\novel-wiki\` 初始化新项目
2. 确认 LLM Provider 已配置（`python -m src.cli llm-providers list`）
3. 启动 server：`python -m src.cli serve --port 8766`（需确保端口未被占用）
4. 获取 project_id：`python -m src.cli project list`
5. 摄入 source 文件：
   - `raw/sources/` 下 6 份文件
   - `Inbox/Processing/` 下 1 份待处理文件
6. 验证分类结果（`wiki/index.md`）

## 自动化分类

Pipeline 会把每份资料自动分为：

| 类型 | 说明 |
|---|---|
| source | 原始授课记录、文档原文 |
| entity | 识别出的创作术语（爽点、节奏、签约条件） |
| concept | 抽象概念（大纲结构、画面感技巧） |
| synthesis | 综合输出（创作知识图谱） |

## 与主项目隔离

- 不同 `project_id`，不同 `.llm-wiki/project.json`
- 不同 `wiki/` 目录，不同 `raw/sources/`
- LanceDB 向量按 `project_id` 隔离，搜索不会跨项目

## 待摄入文件清单

| 文件 | 位置 |
|---|---|
| 必备资料11大纲和细纲.md | raw/sources/ |
| 必备资料11月28号创酷中文网女频现言讲课记录.md | raw/sources/ |
| 必备资料15顺眼谈文章的画面感.md | raw/sources/ |
| 必备资料20个签约条件新人必看2.md | raw/sources/ |
| 必备资料5速度网络文学创作的唯一秘诀.md | raw/sources/ |
| 必备资料8月7日授课记录.md | raw/sources/ |
| 必备资料912怎么写出小说爽点.md | Inbox/Processing/ |

## 步骤

1. 初始化项目
2. 确认 LLM provider 配置
3. 启动 server
4. 摄入 7 份原始资料
5. 验证分类结果
