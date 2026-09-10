# v2 → ruflo-kb 迁移执行

- 源：`D:/5- 项目/000-Nico/LLM_Knowledge_base_v2`；目标：`knowledge/video-notes-wiki`。
- 并行拆分为 V6 持久化、manifest/state、Wiki 转换、raw/pending、向量重建五包，再由集成包收口。
- `migration-20260910` 已完成内容迁移：manifest 5,138 项，raw 3,056，wiki 2,082，archived 637，pending 155，quarantined 1，skipped 16。
- raw SHA-256：0 missing、0 mismatch；H1/H2/H4/H5：0 issues，HEALTHY；聚焦测试 120 passed。
- 向量 dry-run：1,924 页 / 6,136 chunks；正式重建因未配置 embedding provider 暂停，不能宣称完成。
- 本机 CLI 用 UUID 解析项目会受注册表目录 WinError 5 影响；健康检查应直接传目标项目路径。
- 后续故障演练发现并修复 resume 未跳过已完成 staging 输出、raw checkpoint 文件名限制、promotion 前碰撞可能部分写入、以及 promotion 后缺少可回滚记录；新增 8 个恢复/回滚/碰撞测试。
- 迁移器已增加 G8 磁盘预检、apply 开始与 promotion 前源哈希复核，以及 migration_report/migration_warnings/pending_decisions CSV；当前资源预检明确为 8.75GB 需求 / 3.61GB 可用，拒绝 apply。历史批次已非破坏性回填 promotion 记录，rollback dry-run 识别 5,301 条路径。
