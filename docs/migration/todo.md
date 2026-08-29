# Knowledge Compiler 剩余任务 TODO

执行规则：每项先写最小测试，再实现，再运行验证；未满足验收条件不得标记完成。

| 编号 | 任务 | 验收标准 | 状态 | 依赖 |
|---|---|---|---|---|
| B-01 | Agent Retrieval Contract | 真实搜索可用；新页面返回 block Evidence；旧页面显式 legacy | 已完成 | C 阶段 |
| B-02 | 全格式 Canonical Adapter | Markdown/TXT/URL/HTML/PDF/DOCX/XLSX/SRT/VTT 最小样例、失败门禁和 block 定位 | 已完成（最小） | B-01 |
| B-02.1 | PDF 文本样本与页级 block | PDF 含文本；页标记可定位；Evidence 可命中对应 block | 已完成 | pypdf |
| B-02.2 | PDF/DOCX/XLSX 失败样例收口 | 非法输入 fail-closed；不产生发布对象 | 已完成 | B-02.1 |
| B-03.1 | 历史迁移 dry-run | 只读扫描；报告含总量/成功/失败/legacy/未迁移 | 已完成 | C-05 |
| B-03.2 | 分批与断点续跑 | 重跑跳过已完成项；失败清单可恢复 | 已完成 | B-03.1 |
| B-03.3 | 迁移报告回归 | 两次 dry-run 结果稳定；不写 Wiki | 已完成 | B-03.2 |
| B-03.4 | 重复 Document 来源引用 | 共享 document ID；Projection 保留全部 source refs | 已完成 | B-03.3 |
| B-03.5 | Writer 接入 source_refs | 已验证写入、未验证拒绝、读取后来源完整 | 已完成 | B-03.4 |
| B-04 | Runtime/Workflow/Registry 归一 | 仅当 Adapter/Workflow 复杂度达到阈值才启动 | 延后 | B-01/B-02/B-03 |
| B-05.1 | Artifact/凭据/脱敏清单 | 明确风险边界与最小保护措施 | 延后 | B-03 |
| B-05.2 | Queue/Vector 恢复演练 | 有可重复演练脚本和恢复证据 | 延后 | B-05.1 |
| P-01 | 10 文件 Pilot 前检查 | 目标无冲突；项目 Wiki/index 存在 | 已完成 | B-03.5 |
| P-02 | 10 文件真实写入 | 10/10 提交；Evidence 覆盖率 100%；有备份报告 | 已完成 | P-01 |
| P-03 | Pilot 提交后验收 | 10 页 verified；10 页有 Evidence/source_refs；搜索可回读 | 已完成 | P-02 |
| T-01 | 实例规范检查 | 扫描现有实例并输出兼容状态 | 已完成 | 模板规范 |
| T-02 | 兼容迁移报告 | 输出版本漂移、结构缺失和只读迁移建议 | 已完成 | T-01 |

当前策略：B-03 dry-run 已完成；3 个 JSON 非目标文件已排除，36 个重复 document ID 按“共享 Document、保留多 source 引用”处理，但在 Writer 支持该策略前禁止实际写入。B-04/B-05 不因“以后可能需要”提前实现。
