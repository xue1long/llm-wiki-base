# V7 Control Plane Refactor — Ledger

> 本目录是 `docs/superpowers/plans/2026-09-15-v7-ingestion-pipeline-control-plane-refactor.md`
> 的执行账本。每完成一个 Wave/Task,由主 agent 在本目录追加 `progress.md`、
> 调研报告、smoke 记录、最终审查记录。

## 目录约定

```
.superpowers/sdd/2026-09-15-v7-ingestion-pipeline-control-plane-refactor/
├── README.md           # 本文件(索引)
├── progress.md         # Wave/Task 完成状态、commit hash、阻塞原因
├── wave0/              # Wave 0 准备产出
│   ├── prerequisites.md    # A1-A7 逐条核对结果 + 当前代码快照
│   ├── stage6-investigation.md  # H6 加固:Stage 6 调研输出
│   ├── conflict-table.md   # 冲突表(含测试文件 import 依赖)
│   └── plan-baseline-diff.md   # §1.5 现状快照与 git grep 差异
├── wave1/              # Wave 1 三 lane commit 记录 + 各自定向测试结果
├── wave2/              # Wave 2 unified ExtractionResult commit + review 记录
├── wave3/              # Wave 3 WikiWriter + source checkpoint commit + review
├── wave4/              # Wave 4 smoke + 文档 + 最终 review
└── audit/              # plan-audit 审计与整改记录
    ├── round1.md       # 第一轮全面漏洞审计原始输出
    ├── round2.md       # 第二轮压力测试原始输出
    ├── remediations.md # 整改落实清单(对应 plan §9.4)
    └── r2-review.md    # R2 复审(§7 清单逐条勾选)
```

## Wave 0 准备状态

- **BASE commit:** 见 `wave0/prerequisites.md`
- **A1-A7 启动前置条件核对:** 见 `wave0/prerequisites.md`
- **R2 复审清单(§7):** 待 Wave 2 启动前在 `audit/r2-review.md` 完成
