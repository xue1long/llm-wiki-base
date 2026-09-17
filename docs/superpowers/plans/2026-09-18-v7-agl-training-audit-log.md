# V7 AGL Training Plan Audit Log — Round 1 + Round 2

**关联 plan**: `docs/superpowers/plans/2026-09-18-v7-agl-training.md`(v1.0 初稿)

**Round 1 全面漏洞审计 + Round 2 压力测试推演**:合计 40 个问题(5 ① 致命 + 30 ② 重大 + 5 ③ 优化)。

整改后 v2.1 已写入主 plan 文件。本日志作为审计轨迹档案。

## Round 1 问题清单(9 维度, 25 个)

### 维度 1: 目标对齐(Goal Alignment)
- **P1.1** [① 致命] 训练"质量更高"缺基线对比 — 整改方案: 加 V7-baseline

### 维度 2: 前提假设(Assumptions)
- **P2.1** [② 重大] V2 路径可能被 V3 整改替换 — 整改方案: 加前置验证 `V7_USE_V3=false` 路径
- **P2.2** [② 重大] GPU 规格未明 — 整改方案: §十一 加 GPU 规格表
- **P2.3** [② 重大] AGL 烟测深度不够 — 整改方案: §十一 加 4 项 checklist

### 维度 3: 边界场景(Boundary Scenarios)
- **P3.1** [① 致命] 1 raw → 多 topic 导致梯度稀释 — 整改方案: 训练拓扑改为 1 rollout = 1 topic
- **P3.2** [② 重大] Stage1/3/4 走 Gateway 污染训练 — 整改方案: Stage1/3/4 走 frozen provider,不走 AGL Gateway
- **P3.3** [② 重大] 空 topics / 失败 LLM 无 fallback — 整改方案: 加 fallback,空 topics 时 reward=0 但 SUCCEED
- **P3.4** [③ 优化] max_tokens 可能不够 — 整改方案: max_tokens=8192

### 维度 4: 依赖项(Dependencies)
- **P4.1** [② 重大] minimax 配置未确认 — 整改方案: §十一 加 checklist
- **P4.2** [② 重大] wandb 项目未确认 — 整改方案: §十一 加

### 维度 5: 风险与副作用(Risks & Side Effects)
- **P5.1** [① 致命] CONCEPT_SLOTS 改 8 项破坏 candidate pipeline — 整改方案: 验证 + 同步改
- **P5.2** [② 重大] 训练 cost 污染 metric — 整改方案: 单独 AGL cost 记录
- **P5.3** [② 重大] page_synthesizer 镜像常量易漏改 — 整改方案: 常量合并到 constants.py
- **P5.4** [② 重大] post_process_page 默认值导致已有 wiki 被强制重写 — 整改方案: 默认 None

### 维度 6: 可执行性(Feasibility)
- **P6.1** [② 重大] WikiWriter 参数顺序风险 — 整改方案: post_process_page 作为 setter 方法
- **P6.2** [② 重大] ProviderRegistry thread-unsafe — 整改方案: 不改 ProviderRegistry,Stage5 独立 provider
- **P6.3** [② 重大] AGL proxy URL 拼接错误 — 整改方案: env var 修正
- **P6.4** [③ 优化] 训练样本去重/版本缺失 — 整改方案: 加 manifest 锁定

### 维度 7: 验收标准(Acceptance Criteria)
- **P7.1** [② 重大] spot-check 评分 rubric 未定义 — 整改方案: 8 slot × 5 维度
- **P7.2** [② 重大] LLM-judge prompt 未明 — 整改方案: 8-slot concept 版本 prompt

### 维度 8: 盲区清单(Blind Spots)
- **P8.1** [② 重大] novel-wiki raw 分布未调研 — 整改方案: §十三 列出 10 条具体文件名
- **P8.2** [② 重大] Windows 装包测试未做 — 整改方案: §十一 加前置验证步骤
- **P8.3** [③ 优化] 8-slot fixture 适配未评估 — 整改方案: §五 PR-A 加 grep 评估

### 维度 9: 回滚预案(Rollback)
- **P9.1** [② 重大] 硬回滚不撤销 wiki 变更 — 整改方案: AGL 默认写 `_agl/` 子目录,人工审核 move
- **P9.2** [② 重大] 软回滚不释放 GPU — 整改方案: 加 stop_agl_training.sh

## Round 2 问题清单(5 路径 + 雪崩, 15 个)

### 路径 1: 人员缺位
- **PT1.1** [② 重大] 用户无法持续 spot-check — 整改方案: 连续 2 轮缺位 → 暂停
- **PT1.2** [② 重大] API 预算耗尽 — 整改方案: 加 budget monitor + 降级到 ollama 本地

### 路径 2: 资源不足
- **PT2.1** [② 重大] GPU OOM / 被抢占 — 整改方案: 降级到 1.5B + gpu_memory_utilization 0.4
- **PT2.2** [② 重大] raw 编码异常 — 整改方案: 前置 file -i 检测

### 路径 3: 接口报错
- **PT3.1** [② 重大] AGL Gateway 重启状态丢失 — 整改方案: systemd 守护 + wandb 同 run 续传
- **PT3.2** [② 重大] vLLM 5xx 错误污染 — 整改方案: vLLM 健康检查 + pause
- **PT3.3** [① 致命] provider.base_url 修改不生效(silent bug)— 整改方案: Stage5 独立构造 OpenAIProvider

### 路径 4: 超时
- **PT4.1** [② 重大] 多 topic 单 raw 超时 — 整改方案: 训练拓扑改为 1 rollout = 1 topic + timeout_seconds=1800
- **PT4.2** [③ 优化] LLM-judge 评估超时 — 整改方案: hold-out 起步 30 条

### 路径 5: 突发变更
- **PT5.1** [② 重大] V7 整改 plan 并行合入冲突 — 整改方案: 时间窗口隔离
- **PT5.2** [② 重大] schema.md 中途修改 — 整改方案: git tag 锁定
- **PT5.3** [② 重大] 用户训练目标漂移 — 整改方案: 每轮 decision gate

### 雪崩场景
- **S1** [② 重大] vLLM 不稳定导致训练污染 — 整改方案: error rate >5% pause
- **S2** [① 致命] ProviderRegistry thread-unsafe — 整改方案: 不修改全局,Stage5 独立实例
- **S3** [② 重大] V7 整改合入 ImportError — 整改方案: 时间窗口隔离 + rebase
- **S4** [② 重大] Wandb 故障训练盲飞 — 整改方案: 本地 tensorboard 备份

## 整改后复审清单

待 subagent (P5.1 + raw 分布) + (provider + AGL proxy URL) 完成后,基于事实重写 plan v2.1。