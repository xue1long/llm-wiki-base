# A-1 KU Dry-Run 报告（路线 §A-1, F-3 整改 / H-5 ADR-002）

- 项目根: `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki`
- wiki 页面总数: **4892**
  - 其中 unknown (无 frontmatter / 无 type 字段): 2
- 叙述类页面 (CLAIM/SYNTHESIS/DECISION/PROCEDURE/EVENT): **66**
- 叙述类估算上限 (40%): 1957

## 1. PageType 分布

| PageType | 数量 |
|---|---|
| claim | 10 |
| concept | 2234 |
| entity | 1341 |
| source | 1251 |
| synthesis | 56 |
| unknown | 2 |

## 2. 叙述类页面长度分布

| 指标 | 值 |
|---|---|
| 数量 | 66 |
| 最短 (tokens) | 6 |
| 最长 (tokens) | 1769 |
| 平均 (tokens) | 728.1 |
| 中位 (tokens) | 741 |

## 3. 抽样 20 个叙述类页面（手工评估建议）

> ⚠️ **本脚本仅提示抽样清单，不做评估**. 由人工按 H-5 ADR-002 §"答案不明确的判定规则" 评估.

1. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_05fc0c24df52f8e3ced07812.md`
2. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_06f726f51e6bbd12297ff5ca.md`
3. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_3f14555774841e604fad216c.md`
4. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_43c875cbcad6b2cfa382a81c.md`
5. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_450887109cce46bd10f93dbd.md`
6. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_83d9539e4f709f655ad4f54f.md`
7. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_86c998fdf498ec3f12bf4cbc.md`
8. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_8c1ad0aa7e36fd1819cfc745.md`
9. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_a6f8656936192505d9c52896.md`
10. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\claims\pilot_d3c57e79816e58d6647d250e.md`
11. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\东方玄幻创作中的中国古典典籍应用指南.md`
12. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\中国古代行政区划沿革综述.md`
13. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\中国少数民族五大源流综述.md`
14. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\中国现当代小说人物分析案例综述.md`
15. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\书名选取方法综述.md`
16. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\人物塑造综合技法-动机构建与性格转变.md`
17. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\人物鲜活三法综述-履霜知寒-随境动静-含章王事.md`
18. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\人身-36-致命穴详解.md`
19. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\传统小说理论-描写技法综述.md`
20. `D:\5-Project\2026814\llm-wiki-base.bak.20260822\knowledge\novel-wiki\wiki\synthesis\侦探小说开局模式与读者性别偏好综述.md`

## 4. Backfill 成本估算（与 H-5 一致）

| 选择 | 描述 | 成本 (CNY) |
|---|---|---|
| choice_1 | 不拆 | 0 CNY |
| choice_2 | 长叙事类 (>5 段) 全量 LLM 拆分 | 978 CNY |
| choice_3 | 仅"答案不明确"页面 LLM 拆分 | 4 CNY |

**默认 = `choice_3`** （H-5 ADR-002 推荐）

choice_3 比 choice_2 节省: **974 CNY (100%)**

## 5. 下一步

- [ ] 用户在 3 个自然日内决策 choice_1/2/3 (H-5 ADR-002 §Decision)
- [ ] 超时 → 自动采用 choice_3 (H-5 ADR-002 §Decision)
- [ ] 决策后由 A-1 主任务执行实际 backfill

## 参考

- `docs/adr/2026-08-26-ku-split-strategy.md` (H-5 ADR)
- `docs/superpowers/plans/2026-08-26-kc-spec-roadmap.md` §A-1 + F-3
- `scripts/kc_ku_cost_estimator.py` (H-5 成本公式来源)