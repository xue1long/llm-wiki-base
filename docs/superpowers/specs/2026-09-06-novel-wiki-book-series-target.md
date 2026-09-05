# novel-wiki 书系目标方案：三本主教程 + 参考库

**状态：** 整改版，仍需通过前置数据门和样章验证。
**适用对象：** `novel-wiki` 写作知识库（教程、素材、规则、案例、来源关系混合）。  
**替代关系：** 本方案替代“单书五卷”的目标结构；原有规则版编译仍保留。

## 零、前置决策门（未通过不得定案）

“三本主教程 + 参考库”是待验证的候选结构，不是不可变结论。编码前必须生成带快照 ID 的基线报告：

1. 每个候选 book 的 eligible page 数、来源覆盖率、重复率、预估正文长度和至少一条前置—产出学习链；
2. 每个候选 book 至少有 6 个可执行 reader task，且不存在连续两章无可验证出口产物；
3. 任一本书来源覆盖率低于 80%、可归属页面少于 20 个或无法形成最小学习闭环时，执行合并、降级为参考库或取消该书，不得用 LLM 填充；
4. 目标读者、外发授权、MiniMax 预算和参考库依赖策略必须由负责人签字确认。

基线未通过时，系统只允许生成 `rule_only` 报告，不得生成叙事版 outline 或调用远程 Provider。

## 书系数据契约

书系使用独立的 `series-manifest-v1`，与旧 `outline-v1` 并行兼容：

```json
{
  "schema_version": "series-manifest-v1",
  "series_id": "writing-craft",
  "release_id": "...",
  "status": "partial",
  "books": [{
    "book_id": "writing-foundations",
    "required": true,
    "status": "ready",
    "outline_id": "...",
    "hard_dependencies": [],
    "soft_dependencies": ["writing-reference"]
  }]
}
```

`status` 只允许 `draft → partial → ready` 或 `draft/partial → invalid`；系列 `ready` 要求同一 release 批次内所有 `required=true` 的书均为 `ready`。书系 manifest、书 manifest、outline、sidecar 和正文分别校验哈希；任一校验失败均保留旧指针。

旧 release 没有 `series_id` 时按单书兼容读取，不能猜测其属于哪本新书。

## 一、调研结论

公开出版社和作者资料显示，写作类书籍通常有三种组织方式：

| 观察 | 证据 | 对本项目的约束 |
|---|---|---|
| 单本书围绕一个明确承诺 | [Save the Cat! Writes a Novel](https://www.penguinrandomhouse.com/books/554039/save-the-cat-writes-a-novel-by-jessica-brody/) 以 15 个节拍和 10 类故事类型解决情节组织问题 | 一本书必须有单一读者结果，不能把素材、结构、发布混成一个目标 |
| 书系按技能拆分 | [Write Great Fiction Series](https://www.penguinrandomhouse.com/series/0H6/write-great-fiction/) 分为 Plot & Structure、Description & Setting、Characters、Dialogue 四本 | 页面数量大且主题异质时，应按能力域拆书，书内再分卷 |
| 教程与练习相互配套 | [The Storyteller’s Workbook](https://books.google.com/books?id=lftjEAAAQBAJ) 将规划、写作、修改、投稿配成工作表和检查清单 | 练习必须是章节产物；必要时独立为参考/练习库，不挤占正文 |
| 写作书可以用叙事框架承载方法 | [On Writing](https://stephenking.com/works/nonfiction/on-writing-a-memoir-of-the-craft.html) 将回忆、工具、情节、人物、工作习惯放在一个作者叙事框架中 | 叙事化适合解释方法，但不能替来源事实背书 |
| 出版目录会区分 craft、pedagogy、revision、genre 等子域 | [Bloomsbury Creative Writing](https://www.bloomsbury.com/us/academic/creative-writing/) | `novel-wiki` 的教程正文与规则/素材索引必须分层 |

这些案例不是“必须照抄”的模板，但共同说明：**书的边界应由读者要完成的任务决定，而不是由现有页面目录决定。**

## 二、最终书系结构

### A. 三本面向读者的主教程

| book_id | 书名（暂定） | 读者承诺 | 书内卷 |
|---|---|---|---|
| `writing-foundations` | 《从素材到故事》 | 把观察和零散素材变成主题、冲突与可执行大纲 | 1. 观察与采材；2. 主题与立意；3. 结构与大纲 |
| `story-craft` | 《把故事写出来》 | 把大纲落实为人物、场景、章节和可读语言 | 1. 人物与欲望；2. 场景、视角与对白；3. 节奏、悬念与章节推进 |
| `revision-release` | 《从初稿到成稿》 | 发现问题、完成修改，并安全地交付或发布作品 | 1. 语言与段落；2. 结构诊断与反馈；3. 版权、平台与版本迭代 |

不预设每本书的章数。章边界由 reader task、出口产物、前置依赖和页面覆盖共同决定；篇幅超出单章预算时拆章，内容不足时合并或转入参考库。10 章只用于一次连续试跑，不是书籍永久配置。

### B. 一个可选的参考库

`writing-reference` 不按叙事教程编排，保留 `rule_only` 或 `encyclopedic` 模式，包含：

- 写作素材与案例索引；
- 术语、规则、反模式和模板；
- 全量来源、标签、页面关系和检索入口。

参考库不强行承担“读完后能写出作品”的承诺。主教程引用参考库时必须声明依赖类型：`hard` 依赖缺失会阻断发布，`soft` 依赖缺失时正文必须提供自足解释。参考库同样执行来源、敏感信息和完整性校验，只是不调用叙事润色。

## 三、书系层级和归属规则

固定层级：

```text
series
└── book
    └── volume
        └── chapter
            └── section
```

每个 eligible page_id 必须有一个 `primary_book_id` 和一个 `primary_chapter_id`，可有多个 `secondary_topics`，但正文只能渲染一次。归属裁决按：页面类型 → reader promise 关键词 → 前置/出口依赖 → 来源完整度 → 人工裁决；每次裁决写入理由和操作者。跨书内容只产生 `supports`、`required_by`、`contrasts`、`related` 链接，不复制正文。无法归属的页面进入参考库或 `unattributed` 挂账，禁止硬塞进主教程。

跨书关系必须形成无环依赖图；发布前检测环、悬空目标、跨 outline 版本引用和已归档目标。关系索引绑定 `release_id` 与 `outline_id`，旧版本不回写。

每章必须声明：

- `reader_promise`：读者完成本章后能完成什么；
- `entry_requirements`：需要先掌握什么；
- `exit_artifact`：读者应产出什么（如主题句、人物卡、章节大纲、修改清单）；
- `content_roles`：方法、案例、示范场景、练习、反模式；
- `source_page_ids`、`chapter_relations` 和 `unattributed_page_ids`。

## 四、正文形态

主教程每章使用固定阅读节奏：

1. **写作问题场景**：明确标记真实案例或合成示范；
2. **方法解释**：定义、步骤、适用条件、反模式；
3. **案例对照**：引用 Wiki 页面或参考库条目；
4. **读者练习**：产生可检查的中间成果；
5. **来源与下一步**：脚注、来源页、前置/后续章节、相关章节。

示范场景可以叙事化，但不得凭空添加姓名、地点、日期、统计数字或事件。事实段落必须绑定现有 block/page evidence。参考库不调用叙事润色，避免把索引材料伪装成教程故事。

## 五、LLM 和发布边界

- `rule_only`：默认，适用于参考库和旧版 release；
- `narrative_draft`：主教程单章或小批草稿，命令为 `--narrative --use-llm --polish`，不改变 `CURRENT.json`；
- `narrative`：所有章节、来源、关系和质量门通过后，命令加 `--apply` 才能发布；
- 外发前只发送当前章节的最小输入、项目根目录 allowlist 内的相对来源路径；敏感字段脱敏或拒绝外发；
- 每本书独立 staged release，单本失败不阻塞其他书，也不能更新失败书的 `CURRENT.json`；
- 系列 manifest 只记录书间关系和版本，不把任一失败书标记为已发布。

正式发布门槛：全书页面级来源覆盖率 ≥95%，且每章来源覆盖率 ≥80%、关键事实段落 100% 有证据；非命名空间关系 unresolved ≤5% 且无依赖环；所有事实段落有证据，每章至少一个练习和三个检查项，所有产物完整性哈希通过，且通过人工读者任务验收。章节级硬门不能被全书平均值抵消。上述阈值是 pilot 前冻结的初始门槛；若基线证明不适用，只能在 pilot 前经负责人批准调整并记录新分母，不能在生成后为通过而回调。

系列发布还必须满足：必需参考库已发布或所有依赖均为 `soft`；三本书 manifest 来自同一 release 批次；部分成功只能标记 `partial`，不能标记系列完成。

## 六、首轮验证方式

不要从 1749 页随机抽 10 章，也不预先承诺一定存在 10 个合格章节。首轮在基线报告中选择一条连续学习链，目标为 10 章；若合格内容不足，缩短为实际可验证长度并记录原因。优先验证 `writing-foundations` 的“素材 → 主题 → 结构”阅读链：

- 观察与采材；
- 主题与立意；
- 结构与大纲；
- 每章必须有可保存的出口产物，并由下一章显式消费或解释。

样章验收通过后，再分别从另外两本书各选 3–5 章做小批试跑。任何一本书出现来源缺失、关系断裂、LLM 截断、章节目标不一致或练习不可执行，只回退该书的规则版。

## 七、不采用的方案

- **一本书五卷：** 主题跨度过大，读者承诺不清，素材和规则会稀释教程主线；
- **五卷直接拆五本：** 每本过薄，重复的基础概念会被复制，维护成本高；
- **所有页面都叙事化：** 会把索引、规则和未归属素材包装成虚假的连续叙事；
- **先全量生成再验收：** 成本、错误定位和回滚范围都不可控。
