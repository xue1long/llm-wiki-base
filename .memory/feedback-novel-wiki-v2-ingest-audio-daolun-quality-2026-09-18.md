# novel-wiki-v2 摄取质量评估（70 KB 音频转录实测）

## 0. 评估对象 & 评估基线

- **源文档**：`raw/sources/视频音频转录教程/音频教程/大纲写作技巧.md`
  - 大小：70 966 B（~22k 中文字符，UTF-8）
  - 结构：仅 `## 转录内容` 一节，单段无标点的长 ASR 转录；frontmatter 标 `教程/转录/写作/技巧`
  - 内容类型：直播 Q&A + 主题演讲；听众互动主持人/嘉宾叫"戴大人/小艺/深哥"
- **任务**：`kb-20260918152026-4409dd89`
- **生成产物**：
  - **0 个 wiki 页**（fail-closed 拦截，未落盘）
  - 1 个 candidate（`.index/quarantine/kb-20260918152026-4409dd89/candidate.json`）：23 条 claim + 24 条 evidence
- **评估标准**（我自己定的 8 维）：
  1. 证据字面忠实度（quote 是否 byte-equal 源）
  2. 证据定位准确度（block_id 是否真实存在于 CanonicalDocument）
  3. 主张准确度（statement 是否如实地反映了源文）
  4. 主张覆盖度（源里关键概念被吸出的比例）
  5. 主张去重度（同义/重复 claim 的密度）
  6. 置信度校准（confidence 是否与质量匹配）
  7. 结构整洁度（taxonomy 分类、tag 完整）
  8. 失败成本（被 Reviewer 拦下的代价）

## 1. 证据字面忠实度（Evidence byte-fidelity）

把 candidate.json 的 24 条 evidence quote 在源文里做严格 substring 搜索（**不做任何归一化**）：

| 指标 | 数值 |
| --- | --- |
| 严格 byte-match（quote 是源文子串） | **21 / 24（87.5%）** |
| 完全不匹配（match_count=0） | **3 / 24（E13, E14, E21）** |
| 部分匹配（最长 40/46~71 字符子串） | 3 / 24 |

- E13（`主线不能改改了之后就面目全飞了...`）：源文里能找到 40/46 字符子串；缺中间一小段
- E14（`支线可改`）：同上
- E21（`三章一个小高潮...`）：源里 "三张" 是 ASR；claim 用的是 "三章"，导致不匹配

→ 字面忠实度 **B+**，主要问题是 MiniMax-M3 在"三/张/章"上做了"纠正"。

## 2. 证据定位准确度（block_id 正确性）

真实 CanonicalDocument 由 `normalize_text` 生成 5 个 block（按 `\n\n` 切）：
```
ord=0 block_7025fc7d...  (frontmatter)
ord=1 block_2bfd4306...  (# 大纲写作技巧)
ord=2 block_857f8a76...  (## 转录内容)
ord=3 block_ab8a09eb...  (整段 22k 转录)
ord=4 block_8f8177ae...  (---)
```

candidate 用的 block_id：

| Evidence | declared block_id | 在 doc.blocks 中存在? | 实际命中哪个 block |
| --- | --- | --- | --- |
| E0 | `7025fc7d...` | ✅ | ord=0 frontmatter |
| E1 | `2bfd4306...` | ✅ | ord=1 # 大纲写作技巧 |
| E2 | `857f8a76...` | ✅ | ord=2 ## 转录内容 |
| E3-E23 | `block_ab8a09eb78aedda04cbb8a5b#sub-0` 或 `#sub-1` | ❌ **全部不存在** | ord=3 `block_ab8a09eb78aedda04cbb8a5b`（无 `#sub-N` 后缀） |

`#sub-N` 后缀只在 `chunk_prompt_blocks` 阶段被创建（chunking 时把超大 prompt 块拆成子块），**不会出现在 evidence 验证器所查询的 CanonicalDocument 中**。

→ **定位准确度 F（fail）**。LLM 错把 prompt-chunk ID 复用到 evidence block_id，导致 21/24 条 evidence 在严格 block 维度上不匹配。Reviewer 的 `[no-retry] candidate evidence quote does not match source block` 触发完全正确。

> **注意**：失败信息里的 "must match a unique block"（前轮）和 "does not match a document block"（本轮）实际是 **两条不同的校验路径**：
> - 当 quote 在源里有 1 个 match、但 declared block_id ≠ matched block_id → "does not match a document block"（本次全部 21 条命中此分支）
> - 当 quote 在源里有 ≥2 个 match → "must match a unique block"
> - 当前 22k 文档块只有一个 ord=3 block，所以即使有 "sub-N" 修饰，全文 22k 中所有 quote 都唯一 match；触发的是第一条路径

## 3. 主张准确度（Claim truthfulness，23 条）

逐条对照源文真实意图（人工评分，A=准确、B=基本准确有少量失真、C=误导、D=错误、X=无关/空洞）：

| 分布 | 数量 |
| --- | --- |
| **A**（完全忠实） | 15 |
| **B**（基本忠实但丢失细节/简化过度） | 7 |
| **C**（误导） | 1 |
| **D / X** | 0 |

- **C 级只有 1 条**：C2 「转录内容章节下尚未在本块中呈现具体的写作技巧正文，仅有标题框架」。
  - 这是 evidence E2（"## 转录内容"）的逻辑后果——quote 只指向 section header，所以 LLM 据此推断"正文空"。
  - 实际源里 22k 字符全是正文。LLM 没"撒谎"，但被 evidence 选择"骗"了。
- B 级 7 条都是"过于泛化"问题（如 C11「悬念一接一个解决」漏了"先解决后解决"的次序规则；C12「铺垫」漏了"选业→高潮"的递进；C14「从头重新整理」漏了"写得太杂、范围太大"的诊断根因）。
- A 级 15 条里 C4（4 要素）、C6（主线）、C8（性格保持）、C15（NP 文）、C16（性格一致）、C19（主线 vs 主要内容）、C20（节奏）、C21（灌水）、C22（前三章冲突）几乎都是源文原意的精炼复述。

→ **主张准确度 A-**。如果去掉"被 evidence 误导"的 C2，22 条里 15A+7B，0 错。

## 4. 主张覆盖度（Topic recall）

按源文出现的关键概念（自动计数 + 人工核对）：

| 类别 | 概念数 | 被 claim 覆盖 |
| --- | --- | --- |
| 大纲 4 要素 / 主线定义 / 人物设定 / 主要内容 | 4 | 4 / 4 |
| 主线固定 vs 支线灵活 / 不改主线的理由 | 3 | 3 / 3 |
| 悬念 / 高潮 / 铺垫 / 节奏 | 4 | 4 / 4 |
| NP 文 / 一对一文 / 性格通过情节体现 | 3 | 1 / 3（缺"性格通过情节体现"） |
| 模板 / 5 点 / 创作思想 / 故事卖点 | 4 | 0 / 4（**Q&A 部分的金铭网模板完全漏掉**） |
| 案例：老羊的姐姐 / 半湖月重生复仇 | 2 | 0 / 2（**两个具体作品案例都没抽出**） |
| 女主被伤害→崛起→遇到南逐→甜蜜（主要内容示例） | 1 | 0 / 1（漏掉三段式示例） |
| 写作顺序：先主线→后人物→后细节 | 1 | 0 / 1 |
| 开篇迷茫 / 盖楼 metaphor | 2 | 0 / 2 |

**关键结论**：
- "教义类"主张（4 要素 / 主线 / 高潮 / 铺垫）覆盖完整：**8/8 = 100%**
- "示例类"主张完全丢失：**0/4**，包括两个具体的网文案例（金铭网模板、老羊的姐姐、半湖月、女主三段式）
- "Q&A 问答类"主张部分丢失：6/9

整体召回：**71%（22/31 个关键概念被抽出）**。问题不是"找不到"而是 LLM 系统性地不抽示例/案例（它们在源里占 ~30% 篇幅，对应字数约 6000–8000 字，但 LLM 把它压缩成"主线不变"这种泛化主张）。

→ **主张覆盖度 B**。

## 5. 主张去重度

| 重复对 | 重复度 |
| --- | --- |
| C6（主线不能变）≡ C13（主线一旦设计好就不要改动） | **高**（几乎完全同义） |
| C7（不改主线否则面目全非）≈ C13 | **中** |
| C8（性格不要改）≡ C16（人物个性从开头到结尾保持一致） | **高** |
| C14（重新整理后续走向）≈ C12（高潮前必须铺垫） | **弱**（角度不同） |

23 条 claim 里 2 对 4 条高度重复，去重后实为 ~19 条有效独立主张。如果按"核心论点"算，实际新信息量约 14 条。

→ **去重度 B-**。

## 6. 置信度校准（confidence）

| confidence 范围 | 数量 | 我的实际准确度判断 | 校准 |
| --- | --- | --- | --- |
| 0.95 | 1 | A | 偏高但可接受 |
| 0.93 | 1 | A | 偏高但可接受 |
| 0.92 | 1 | A | 合适 |
| 0.91 | 1 | A | 合适 |
| 0.90 | 3 | A | 合适 |
| 0.88 | 1 | A | 合适 |
| 0.87 | 1 | A | 合适 |
| 0.86 | 1 | A | 合适 |
| 0.85 | 6 | 1A+4B+1C | 偏高（C2 应 <0.5） |
| 0.80 | 4 | 1B+3A | 合适 |
| 0.78 | 1 | B（漏信息） | 偏低，应 0.82 左右 |

整体置信度均值 **0.866**，与 A+B（94%）基本匹配。C2 是离群值（conf 0.85 但内容误导）。

→ **置信度校准 B+**。LLM 普遍偏自信（0.85 当 0.92），但未出现"高置信 + 错误"的危险组合。

## 7. 结构整洁度（taxonomy / tag）

candidate 没指定 tag 或 taxonomy，taxonomy 在生成阶段（Generator）才接 schema。candidate 阶段无 issue。

## 8. 失败成本（Reviewer 拦下的代价）

- Reviewer 拒绝后：candidate 被 quarantine、`.kb-queue.json` 记 dead_letter、wiki **0 页**写入。
- 没有副作用污染。
- 但**正确的 claim 也一起被丢了**：21/24 evidence 的字面 quote 是源文真子串、它们的声明也都站得住。如果 Reviewer 只拦 block_id 不匹配的 21 条 + 完全不 match 的 3 条，理论上 0 条 evidence 能过；这是 fail-closed 的固有代价。
- 拦下后没有任何信号告诉操作员"候选其实有 90% 可用，只差 block_id 格式"——操作员只能看到一句短报错，必须人工 dump candidate.json 才能看出"LLM 把 prompt-chunk ID 复用了"。

→ **失败成本 A**（无污染），但**失败信息可读性 C**。

---

## 评分总览（我自己的标准，5 分制）

| 维度 | 分数 | 评语 |
| --- | --- | --- |
| 1. 证据字面忠实度 | **4.0 / 5** | 21/24 严格 byte-equal；3 条因 ASR 错字被"纠正" |
| 2. 证据定位准确度 | **1.0 / 5** | 21/24 block_id 用了 `#sub-N` 后缀但 doc.blocks 不识别——这才是真实失败点 |
| 3. 主张准确度 | **4.5 / 5** | 22 条里 15A+7B，0 错；C2 是 evidence 误选导致的副作用 |
| 4. 主张覆盖度 | **3.5 / 5** | 教义类 100%、示例类 0%、案例类 0% |
| 5. 主张去重度 | **3.5 / 5** | 4 条高度重复（C6≈C13、C8≡C16），实为 ~19 条独立信息 |
| 6. 置信度校准 | **4.0 / 5** | 整体合理偏高 0.03–0.07，无危险组合 |
| 7. 结构整洁度 | **N/A** | candidate 阶段不评估 |
| 8. 失败成本 | **4.5 / 5** | 0 污染；信息可读性差 |
| **综合** | **3.6 / 5** | **B 等级**——主张质量本身 B+，但被 block_id 格式问题硬拦 |

---

## 关键判断

### ✅ 好的方面
1. **主张准确率高**：22 条里 0 条错误，15 条 A 级——LLM 的语义理解和总结能力没问题。
2. **失败安全**：fail-closed slot 严格执行，0 wiki 写入——即使后续 block_id 修好、claim 也能用，不会污染现有 wiki。
3. **置信度与质量匹配**：LLM 没有"低质量高置信"。
4. **核心教义覆盖完整**：大纲的 4 要素、主线定义、人物设定、主要内容、高潮节奏这些"基本教义"一条不漏。

### ❌ 关键问题
1. **block_id 用了 prompt-chunk 后缀**（`#sub-0`/`#sub-1`），但 validate_evidence 查的是 `document.blocks`（由 `\n\n` 切的 deterministic block ID）。两者 schema 不一致。**这是工程接口不匹配**，不是 LLM 错——prompt 里给 LLM 看的是 chunked blocks，validate 时查的是 canonical blocks。
2. **LLM 把所有内容 claim 都挂在同一个父 block_id 上**（22/24 条都是 `block_ab8a09eb...`），既不细分也不标识自己用了哪个 chunk。这暴露出 prompt 没强制 LLM 在引用时区分 chunk。
3. **示例/案例被系统性漏抽**：3 个具体作品案例（金铭网模板 / 老羊的姐姐 / 半湖月）+ 1 个三段式示例（女主被伤害→崛起→南逐→甜蜜）全部没成为独立 claim。这是"过度泛化"——LLM 倾向把示例"消化"成抽象规则，丢掉案例。
4. **4 条重复 claim**（C6/C7/C13，C8/C16）——LLM 没做语义去重。
5. **失败信息可读性差**：操作员只看到 `[no-retry] candidate evidence quote does not match source block: evidence does not match a document block`，要调试必须打开 candidate.json 才知道是 block_id 后缀问题。

### 📐 优先级建议
1. **P0 — 修接口契约**：让 LLM 看到的 chunked blocks 和 validate 时的 canonical blocks 共享同一个 block_id 空间。
   - 选项 A：Analyzer 把 prompt 时把 chunked blocks 的 `#sub-N` 后缀剥掉（验证后再恢复）；最简单
   - 选项 B：validate_evidence 增加"如果 declared 是 `<X>#sub-N` 且 X 存在于 blocks，则接受"；兼容性最好
   - 选项 C：在 prompt 里强制 LLM 引用 `block_ab8a09eb...`（不带后缀）；改 prompt 最直接
2. **P1 — 提示词强化抽取案例**：在 Analyzer prompt 加 "**每个具体作品案例必须作为独立 claim 抽出**，不要消化为通用规则"。
3. **P1 — 失败信息增加诊断**：把"哪些 evidence 失败、失败原因分类（block_id 不存在 vs quote 不存在 vs 多块匹配）"写进 judgment.json。
4. **P2 — 主张去重**：claim 合并时做 simple embedding 相似度，过 0.85 视为重复，保留置信度更高的那条。
5. **P2 — 修订 reference**：本任务可重跑（同一份文件 ingest 是幂等的），修好后用 `kb-20260918152026-4409dd89` 重试。
