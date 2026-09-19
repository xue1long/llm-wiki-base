# novel-wiki-v2 单文档摄取测试

- 实例：`knowledge/novel-wiki-v2`
- 原始文档：`raw/sources/视频音频转录教程/02进阶视频教程/大纲写作技巧.md`（约 3 KB）
- 任务：`kb-20260918122203-bbce7220`，HTTP 队列链路最终 `succeeded`，生成 4 页（3 concept + 1 source）。
- Provider：MiniMax；embedding 初始化成功。
- 通过项：fields validate、tags validate、H1/H4/H5。
- 质量问题：lint 报 4 项（source processing_depth 不被当前 lint 接受，3 页缺必需 section）；wiki-quality strict 报 36 个结构问题，其中 H2 断链 18 个、重复标题组 1 个；`提纲的重要性` 被判定为 `大纲四要素` 的重复并降级。
- 摄取过程记录 2 个 unresolved taxonomy gap：`taxonomy-写作技法`、`taxonomy-大纲与结构`。
- 2 个 concept 页面仍含模板占位正文，说明当前“流程成功”不等于“内容质量通过”。
