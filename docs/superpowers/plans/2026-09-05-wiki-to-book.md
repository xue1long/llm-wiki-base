# wiki → 网文写作百科全书 Book 编译方案

> 状态：**修订版 v2 — 待审批**  
> 日期：2026-09-05  
> 项目：knowledge/novel-wiki  
> 目标：将 wiki 页面编译为一本结构化的《网文写作百科全书》

---

## 〇、修订说明（v2 vs v1）

v1 方案经 4 角色独立审核（详见 `2026-09-05-wiki-to-book-review.md`），发现 **9 个阻断 + 19 个重要问题**。本版本针对每项问题做了对应修复：

| 审核问题 | 修复位置 |
|---|---|
| 数据口径 1255 vs 1718 矛盾 | §1.1 重构口径表，明确 sources 不纳入 |
| 项目未 init | §0.1 前置条件 |
| 输出目录与 KC book 冲突 | §6 改为 `book-wiki/` |
| taxonomy_summary.txt 不存在 | §三.1 Step 0 统计脚本 |
| scripts/ 违反模块私有 | §九 改为 `src/kc/views/book/wiki/` 子包 |
| page_id 用标题（应使用 wiki 系统 ID） | §三.2 双键标识 + §五.1 校验 |
| SECTION_MAP 精确匹配漏 73% | §四.2 模糊匹配 + 兜底桶 |
| role 覆盖导致空内容 | §四.3 改为按 heading 归桶 + role 仅做排序权重 |
| Step 1 汇总合并易丢失 | §三 改为 chunked 单卷独立合并 |
| Step 3 润色校验只看 wikilink | §五.3 增强为内容守恒校验 |
| 408 无标签无置信度 | §三.3 outline 加 `confidence` 字段 + 兜底卷 |
| LLM provider 未集成 | §九 Task 6 增加 provider 加载 |
| 25 个碎片子类无归并规则 | §三.3 硬约束 7 |
| token 估算乐观 | §七 重算 80k~120k |
| entity/synthesis 渲染错位 | §四.2 重构映射表 + §四.5 重写模板 |
| 与现有 `outline.py` 命名冲突 | §九 改用 `src/kc/views/book/wiki/` 子包 |
| 目录无章节摘要 | §六.3 加入 overview |
| book_id 静态 | §六.2 改为 hash 派生 |
| 测试策略缺失 | §九 每个 task 加测试项 |

---

## 〇.1 前置条件（执行前必须完成）

| 项 | 命令 | 说明 |
|---|---|---|
| 项目初始化 | `python -m src.cli project init knowledge/novel-wiki` | 生成 `.llm-wiki/project.json`，获取 project_id |
| 项目注册 | `python -m src.cli project list` | 确认注册成功 |
| LLM provider 配置 | `python -m src.cli llm-providers add openai-prov openai --api-key $OPENAI_API_KEY` | 为 Step 1/3 LLM 调用准备 |
| LLM provider 设默认 | `python -m src.cli llm-providers set-default openai-prov` | |

> **项目初始化前不要执行 Step 1-4**，否则 `book build` CLI 解析项目会失败。

---

## 一、现状分析

### 1.1 数据规模（统一口径）

| 页面类型 | 数量 | 是否纳入 Book | body 模板 |
|---|---|---|---|
| concepts | 924 | ✅ 全部纳入 | 定义/主要特点/适用场景/反模式/证据强度/例子/相关概念 |
| entities | 316 | ✅ 全部纳入 | 基本信息/简介/写作价值/相关引用 |
| sources | 463 | ❌ **不纳入**（噪声大，与 concepts 重叠） | — |
| synthesis | 15 | ✅ 全部纳入 | 议题与分歧点/各方观点/共识/证据对比/待定与结论 |
| **纳入合计** | **1255** | | |
| 全集合计 | **1718** | | |

**口径说明**：
- "1255" = concepts (924) + entities (316) + synthesis (15)
- "1718" = 上述 + sources (463)
- 整个方案涉及页面数 = **1255**
- manifest.json `total_pages` = **1255
- sources 不纳入的理由：ASR 转录噪声大、74% 内容与 concepts 重叠、纳入会让书篇幅膨胀 1 倍；保留在 wiki/ 作为溯源证据
- **如未来需要纳入 sources，可在 outline.json 里追加 `source_pages` 字段，扩展 Step 2 处理逻辑**

### 1.2 taxonomy 分类分布

| 大类 | 子类数 | 页面数 | 占比 |
|---|---|---|---|
| 写作技法（单标签主分类） | 15 | 540 | 64% |
| (无分类) | — | 408 | — |
| 题材体系 | 11 | 72 | 9% |
| 心态与职业 | 3 | 56 | 7% |
| 平台规则 | 6 | 44 | 5% |
| 读者与市场 | 4 | 38 | 5% |
| 案例与素材 | 4 | 20 | 2% |
| 其他散类（每类 1-3 条） | 25 | 25 | 3% |
| **有标签合计** | **39** | **847** | **68%** |

> 注：847 是有 taxonomy_of 关系的概念页数；一个页面可挂多个标签，但 §1.2 只统计主分类（即 relations[taxonomy_of] 中第一个 target）。

### 1.3 核心矛盾与应对

| 矛盾 | 应对 |
|---|---|
| 「写作技法」独占 540 条 | LLM Step 1 按主题拆成 10-15 章（卷粒度控制：§3.4 约束） |
| 408 个无分类页面（77 concepts + 316 entities + 15 synthesis） | LLM 推断 + 每页加 `confidence` 字段；`confidence < 0.5` 统一进「综合参考」卷 |
| 25 个碎片子类（每类 1-3 页） | §3.4 约束 7：LLM 必须把碎片子类归并到相邻主题章，不单独成章 |
| 页面跨类严重（3-4 个标签/页） | Step 1 每个页面只取主分类，备选分类作为章节内"延伸阅读"标注 |

---

## 二、总体流程

```
┌──────────────────────────────────────────────────────────────────┐
│  Step 0: 项目前置 (一次)                                          │
│                                                                   │
│  • project init / llm-providers add / set-default                 │
│  • 扫描 wiki/ 目录，生成 _taxonomy_summary.txt 和 _pages.jsonl     │
│  • 构造 wiki_pages: {wiki_id → WikiPage} 字典                     │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 1: LLM 单卷独立规划（chunked，避免大合并）                  │
│                                                                   │
│  输入: taxonomy_summary + pages (按 taxonomy 大类切片)             │
│  输出: per_volume_outlines.json (按卷独立规划，每卷一个 outline)    │
│  调用: 1 LLM call per volume (~6-8 calls total)                   │
│  校验: 每卷校验覆盖率，缺页则自动二次调用补全                      │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 2: 规则聚合                                                  │
│                                                                   │
│  输入: per_volume_outlines + wiki_pages                            │
│  输出: 每章原始 Markdown                                            │
│  关键变更: 按 section heading 归桶 + 模糊匹配 + 未匹配兜底          │
│  role 仅为排序权重，不强制覆盖                                     │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 3: LLM 润色（可选，默认开启）                                │
│                                                                   │
│  输入: 每章原始 Markdown + 章概述                                   │
│  输出: 润色后的章节 Markdown                                        │
│  调用: ~40 次 LLM                                                  │
│  校验: wikilink 守恒 + ### 数量守恒 + 段落哈希守恒 + token 数守恒   │
└──────────────────────────────┬───────────────────────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 4: 编译输出                                                  │
│                                                                   │
│  输出: <project>/book-wiki/                                        │
│        manifest.json + 分卷分章 Markdown + 全书目录（含 overview） │
│  调用: 0 次 LLM                                                    │
└──────────────────────────────────────────────────────────────────┘
```

---

## 三、Step 1：LLM 单卷独立规划（修订：避免大合并丢失）

### 3.1 Step 0 准备工作

在 Step 1 调用 LLM 之前，先用本地脚本产出输入文件：

**Step 0.1**：扫描 `wiki/` 目录生成 `_pages.jsonl`：

```python
# src/kc/views/book/wiki/scanner.py
def scan_wiki_pages(wiki_root: Path) -> list[dict]:
    """扫描 wiki/ 输出每页的最小化 JSONL 行：
    {"wiki_id": "card_xxx", "title": "...", "type": "concept",
     "primary_taxonomy": "写作技法", "definition_summary": "..."}
    """
```

**Step 0.2**：统计 `_taxonomy_summary.txt`：

```python
# src/kc/views/book/wiki/taxonomy_stats.py
def build_taxonomy_summary(wiki_root: Path) -> str:
    """按 taxonomy_of 关系统计：每个子类下有多少页面，主分类页面列表（前 10 个）"""
```

### 3.2 双键标识策略

outline JSON 中每个页面用 **双键** 引用，避免角色3指出的"page_id 用标题 vs 系统 ID"问题：

```json
{
  "wiki_id": "card_1795e9a2c_4f1e0a9b_选题与立意",
  "title": "选题与立意",
  "type": "concept",
  "primary_taxonomy": "写作技法",
  "role": "core",
  "confidence": 0.92
}
```

LLM 输入时只用 `title`（人类可读），LLM 输出时也用 `title`；落地校验时**用 `title` 二次查表映射回 `wiki_id`**。映射失败则该页丢弃并触发补全。

### 3.3 单卷独立规划（替代"两批 + 汇总合并"）

v1 的"Batch 1 + Batch 2 + 汇总 LLM 合并"是灾难级风险（B7）。v2 改为：**LLM 按"卷"独立规划，每卷一个独立 LLM 调用，输出一个 per_volume_outline.json**。

#### 3.3.1 输入切片

按 taxonomy 大类切分：

| 卷 | 数据来源 | 页面数（估） |
|---|---|---|
| 卷1 写作基础（选题/大纲/开篇） | concepts 主分类「写作技法」前 1/3 + 部分 | ~180 |
| 卷2 人物与情节 | concepts 主分类「写作技法」中 1/3 + 部分 | ~180 |
| 卷3 文笔与表达 | concepts 主分类「写作技法」后 1/3 + 部分 | ~180 |
| 卷4 题材与流派 | concepts 主分类「题材体系」+ 实体「作品」 | ~140 |
| 卷5 平台与运营 | concepts 主分类「平台规则」+ 实体「平台」 | ~80 |
| 卷6 读者与心态 | concepts 主分类「读者与市场」+ 「心态与职业」 | ~120 |
| 卷7 综合参考（兜底卷） | 无标签概念 + 低置信度 entity + synthesis | ~420 |

> 注：实际切片由 LLM 在 Step 1.0 一次性产出"卷分配方案"决定，下面 §3.3.3 详述。

#### 3.3.2 LLM 调用模式

**Step 1.0 — 卷分配**（1 次 LLM 调用）：

```
输入:
- taxonomy_summary (按主分类聚合的页面分布)
- 408 个无标签页面的 title + definition_summary

输出:
{
  "volumes": [
    {"id": "v1", "title": "写作基础", "page_titles": [...]},
    {"id": "v2", "title": "人物与情节", "page_titles": [...]},
    ...
    {"id": "v7", "title": "综合参考", "page_titles": [...]}  // 兜底卷
  ]
}

约束:
- 6-10 卷（v7 综合参考是兜底卷）
- 每个无标签页面必须有归属，confidence < 0.5 的归入 v7
- 卷总页数相对均衡（200-400 之间）
```

**Step 1.1~1.7 — 每卷独立细化**（每卷 1 次 LLM 调用，共 6-10 次）：

```
输入:
- Step 1.0 给该卷分配的页面列表 (title + definition_summary + primary_taxonomy)
- taxonomy_summary (供 LLM 参考)

输出: per_volume_{id}.json
{
  "volume_id": "v1",
  "title": "写作基础",
  "chapters": [
    {
      "id": "v1-ch01",
      "title": "选题与立意",
      "overview": "...",
      "page_titles": [...]
    }
  ]
}

约束:
- 3-15 章/卷
- 15-50 页/章
- 每章必须有 overview (100-200 字)
- 尊重 page_titles 中的 primary_taxonomy，confidence < 0.5 的归入综合卷
```

### 3.3.3 校验 + 补全

每卷的 LLM 输出后立即校验：

```python
def validate_volume_outline(volume_id, volume_outline, all_pages_in_volume):
    errors = []
    
    # 1. 覆盖校验
    assigned = {p['title'] for ch in volume_outline['chapters'] for p in ch['page_titles']}
    missing = all_pages_in_volume - assigned
    extra = assigned - all_pages_in_volume
    
    if missing:
        # 自动重跑该卷 LLM 调用，补全缺失页面
        errors.append(("missing", missing))
    if extra:
        errors.append(("extra", extra))
    
    # 2. 章页面数 15-50
    for ch in volume_outline['chapters']:
        n = len(ch['page_titles'])
        if n < 10 or n > 60:
            errors.append(("chapter_size", ch['id'], n))
    
    # 3. overview 必有
    for ch in volume_outline['chapters']:
        if not ch.get('overview'):
            errors.append(("missing_overview", ch['id']))
    
    return errors
```

校验失败的卷：**自动重试 2 次**，仍失败的卷进入人工干预队列（输出缺失清单给用户决定）。

### 3.4 LLM 硬约束

1. 每个页面必须分配到且仅到一个章节
2. **每章 15-50 页**（校验阈值收紧为 10-60，提示但不阻断）
3. 卷数 6-10，含 1 个「综合参考」兜底卷
4. 已有 taxonomy 标签的页面，主分类方向尊重原标签
5. **无标签页面必须给出 confidence (0-1)**；< 0.5 归入「综合参考」卷
6. entities 和 synthesis 也要分配，**不要漏掉**
7. **25 个碎片子类（每类 1-3 页）必须归并到相邻主题章**，不允许单独成章
8. synthesis 分配到与其主题最相关的章节
9. 每章必须有 overview（100-200 字）
10. 章标题用简洁中文（如"选题与立意"、"人物塑造"）
11. 输出严格 JSON（用 `response_format={"type": "json_object"}` 强制）
12. `page_titles` 数组中每个元素必须是字符串（不能是对象），保持 schema 简单

### 3.5 LLM 输出 schema

```json
{
  "volume_id": "v1",
  "title": "写作基础",
  "description": "本卷聚焦网文写作的基础流程与方法论，从选题到开篇的全链路。",
  "chapters": [
    {
      "id": "v1-ch01",
      "title": "选题与立意",
      "overview": "本章涵盖网文选题的核心方法论...",
      "page_titles": ["选题与立意", "题材选择方法论", "热门题材分析"],
      "entity_assignments": [
        {"title": "热门题材分析", "role": "case"}
      ]
    }
  ]
}
```

### 3.6 合并 per_volume_outlines

所有卷输出后，机械合并（不用 LLM）：

```python
final_outline = {
  "book_title": "网文写作百科全书",
  "generated_at": <timestamp>,
  "volumes": [load_volume(i) for i in range(1, 8)],
  "page_index": build_global_page_index()  # wiki_id → {volume_id, chapter_id}
}
```

合并时再次校验全局覆盖：

```python
def validate_global_coverage(outline, all_wiki_pages):
    assigned_titles = {
        title
        for vol in outline['volumes']
        for ch in vol['chapters']
        for title in ch['page_titles']
    }
    all_titles = {p.title for p in all_wiki_pages}
    missing = all_titles - assigned_titles
    return missing  # 应为空
```

---

## 四、Step 2：规则聚合（修订：模糊匹配 + 兜底）

### 4.1 页面解析

`src/kc/views/book/wiki/parser.py`：

```python
@dataclass(frozen=True)
class WikiPage:
    wiki_id: str             # 系统 ID (card_xxx)
    title: str
    page_type: str           # concept | entity | synthesis
    primary_taxonomy: str    # 主分类（taxonomy_of relations 的第一个 target）
    confidence: float        # 来自 outline (LLM 推断页面默认 0.3-0.7)
    sections: dict[str, str] # heading → body text (heading 已 normalize)
    relations: list[dict]
    path: Path
```

**heading 归一化**：解析时去掉多余空白、括号、emoji：

```python
def normalize_heading(text: str) -> str:
    text = text.strip()
    # 去除"## 1. " "## （一）" 等序号
    text = re.sub(r'^[\d.、（）()]+', '', text)
    return text.strip()
```

### 4.2 Section 聚合映射（修订：模糊匹配 + 兜底桶）

#### 4.2.1 主映射表（精确匹配）

```python
SECTION_BUCKETS = {
    # === concept sections ===
    '定义': '核心知识点',
    '概念释义': '核心知识点',
    '什么是xx': '核心知识点',
    '主要特点': '核心知识点',
    '特点': '核心知识点',
    '核心要素': '核心知识点',
    '适用场景': '方法与技巧',
    '应用场景': '方法与技巧',
    '使用场景': '方法与技巧',
    '反模式与常见错误': '常见错误',
    '反模式': '常见错误',
    '常见错误': '常见错误',
    '误区': '常见错误',
    '陷阱': '常见错误',
    '例子': '案例参考',
    '案例': '案例参考',
    '示例': '案例参考',
    '举例说明': '案例参考',
    '证据强度': '元数据',
    '相关概念': '相关条目',
    '参考来源': '相关条目',
    
    # === entity sections ===
    '基本信息': '实体卡片',
    '简介': '实体卡片',
    '基本信息与简介': '实体卡片',
    '写作价值': '写作参考',
    '别名': '元数据',
    '相关引用': '相关条目',
    
    # === source sections (若未来纳入) ===
    '来源元数据': '元数据',
    '转录质量': '元数据',
    '摘要': '素材来源',
    '关键观点': '素材来源',
    '可信度声明': '元数据',
    '正文内容': '素材来源',
    '转录内容': '素材来源',
    '抽取的概念': '素材来源',
    
    # === synthesis sections ===
    '议题与分歧点': '综述议题',
    '各方观点': '综述观点',
    '共识': '综述观点',
    '证据对比': '综述观点',
    '待定与结论': '综述结论',
}
```

#### 4.2.2 模糊匹配 fallback

精确匹配失败时，尝试按关键词匹配：

```python
def fuzzy_match_bucket(heading: str) -> str | None:
    h = heading.lower()
    keywords = {
        '核心知识点': ['定义', '特点', '要素', '本质', '是什么'],
        '方法与技巧': ['场景', '用法', '步骤', '方法', '怎么做', '技巧'],
        '常见错误': ['错误', '误区', '陷阱', '反面', '失败', '问题'],
        '案例参考': ['例子', '案例', '示例', '实例', '举例'],
        '综述观点': ['观点', '看法', '立场'],
    }
    for bucket, kws in keywords.items():
        if any(kw in h for kw in kws):
            return bucket
    return None
```

#### 4.2.3 兜底桶

模糊匹配仍失败的 heading，进入「其他内容」桶（不是静默丢弃）：

```python
SECTION_BUCKETS_FALLBACK = '其他内容'
```

#### 4.2.4 bucket 重新分类（修订：role 不覆盖）

v1 中 `role` 字段强制覆盖归类会导致"页归对桶、内容为空"。v2 改为：

- `role` 仅作为该页面**在 bucket 内的排序权重**（pitfall 放桶首位，case 放桶末位）
- 页面所有非元数据 sections 都按各自 heading **归入对应 bucket**
- 一个页面可同时出现在多个 bucket（按 section heading 自然拆分）

```python
ROLE_SORT_WEIGHT = {
    'core': 0,
    'method': 1,
    'pitfall': 2,  # 桶内放最前
    'case': 3,     # 桶内放最后
    'reference': 0,
    'perspective': 0,
}
```

### 4.3 聚合算法（修订）

```python
def aggregate_chapter(chapter_outline, wiki_pages, pages_index):
    """章节聚合 - 按 heading 归桶 + role 排序权重 + 兜底保留"""
    buckets = {b: [] for b in [
        '核心知识点', '方法与技巧', '常见错误', '案例参考',
        '实体卡片', '写作参考', '素材来源',
        '综述议题', '综述观点', '综述结论',
        '相关条目', '其他内容', '元数据'
    ]}
    
    for page_title in chapter_outline['page_titles']:
        page = pages_index.get_by_title(page_title)
        if page is None:
            log_warning(f"页面 '{page_title}' 未找到，跳过")
            continue
        
        role_weight = ROLE_SORT_WEIGHT.get(page.role, 1)
        
        # 按 heading 归桶（不强制覆盖）
        for heading, body in page.sections.items():
            bucket = SECTION_BUCKETS.get(heading)
            if bucket is None:
                bucket = fuzzy_match_bucket(heading)
            if bucket is None:
                bucket = '其他内容'
            
            buckets[bucket].append({
                'page_id': page.wiki_id,
                'page_title': page.title,
                'heading': heading,
                'body': body,
                'role_weight': role_weight,
                'credibility': page.credibility,  # 若有
            })
    
    # 桶内排序：pitfall 优先，case 最后
    for bucket_name, items in buckets.items():
        items.sort(key=lambda x: x['role_weight'])
    
    return render_chapter(chapter_outline, buckets)
```

### 4.4 单知识点渲染

```python
def render_knowledge_point(item: dict) -> str:
    lines = []
    lines.append(f"### {item['page_title']}")
    lines.append(f"> 来源：[[{item['page_id']}|{item['page_title']}]]")
    if item.get('credibility'):
        lines.append(f"> 可信度：{item['credibility']}")
    lines.append("")
    lines.append(item['body'].strip())
    lines.append("")
    return '\n'.join(lines)
```

### 4.5 章 Markdown 模板（修订：按 bucket 分组渲染）

```markdown
# 第{number}章 {章标题}

> 卷：{卷标题} | 章节 ID：{chapter_id}

{overview (200-300字)}

---

{按 bucket 分组渲染，每个 bucket 作为一个 ## section}

例：

## 核心知识点

### 概念A
> 来源：[[card_xxx|概念A]] · 证据强度：强

[定义段内容]

[主要特点段内容]

### 实体X
> 来源：[[card_yyy|实体X]]

[基本信息段 + 简介段]

---

## 方法与技巧

### 概念B
> 来源：[[card_xxx|概念B]]

[适用场景段内容]

---

## 常见错误

### 概念C
> 来源：[[card_xxx|概念C]]

[反模式段内容]

---

## 案例参考

### 概念D
> 来源：[[card_xxx|概念D]]

[例子段内容]

---

## 相关条目

- [[card_xxx|条目1]] — [从 relations 中提取]
- [[card_xxx|条目2]] — [从 relations 中提取]

---

## 元数据

- 来源页面数：{n}
- 证据强度分布：强 {x} 条 / 中 {y} 条 / 弱 {z} 条
- LLM 分类置信度：mean={μ}, min={min}
```

> **空 bucket 不渲染 section**，避免空标题；「其他内容」bucket 仅在有内容时渲染。

---

## 五、Step 3：LLM 润色（修订：内容守恒校验）

### 5.1 任务定义

对 Step 2 产出的原始聚合 Markdown 做润色：
- 扩写 overview 到 200-300 字
- 调整 bucket 内排序（按"先概念后实例 / 先通用后专项 / 先基础后进阶"）
- 每组末尾加承上启下句
- 最后加「本章小结」section

**不新增、不删除、不修改实质内容**。

### 5.2 LLM Prompt

```
你是网文写作百科的编辑。以下是"{卷标题} · {章标题}"章节的原始聚合内容。

请做以下润色（必须严格遵守）：

1. 将章节开头的 overview 扩写到 200-300 字，说明本章涵盖的核心问题和知识脉络。

2. 在每个 bucket（## 标题）分组内，将知识点按以下逻辑重新排序：
   - 先概念后实例
   - 先通用后专项
   - 先基础后进阶

3. 在每个 bucket 末尾加 1-2 句承上启下说明（用斜体标注，如：
   *以上是本章的基础理论，下面进入方法与技巧层面。*）。

4. 在文末加「## 本章小结」section，用 3-5 句话概括本章核心要点。

硬性约束（违反则输出无效）：
- 不能新增任何 wikilink（`[[xxx]]`）—— 所有 wikilink 必须来自原文
- 不能删除任何 wikilink
- 不能删除任何 ### 标题
- 不能修改任何段落的实质内容（可在不影响原意的前提下微调措辞，但段落字数变化 ≤ ±15%）
- 不能凭空添加事实、数据、案例、引语

润色前内容：
{chapter_markdown}

输出严格 JSON：
{
  "polished_markdown": "...",
  "changes_summary": "本次润色做了哪些调整"
}
```

### 5.3 输出校验（修订：内容守恒）

```python
def validate_polished_chapter(original: str, polished: str, chapter_id: str):
    errors = []
    
    # 1. 来源标注守恒（wikilink 集合必须子集）
    orig_refs = set(re.findall(r'\[\[([^\]|]+)', original))
    pol_refs = set(re.findall(r'\[\[([^\]|]+)', polished))
    if orig_refs - pol_refs:
        errors.append(("lost_refs", orig_refs - pol_refs))
    bad_new = pol_refs - orig_refs - {'本章小结'}  # 新增的 wikilink 必须不存在
    all_page_ids = load_all_page_ids()
    if bad_new - all_page_ids:
        errors.append(("invalid_new_refs", bad_new - all_page_ids))
    
    # 2. ### 标题数量守恒（不能删除 H3）
    orig_h3 = set(re.findall(r'^### (.+)$', original, re.MULTILINE))
    pol_h3 = set(re.findall(r'^### (.+)$', polished, re.MULTILINE))
    if orig_h3 - pol_h3:
        errors.append(("lost_h3", orig_h3 - pol_h3))
    
    # 3. 段落哈希守恒（关键内容不能被改写或删除）
    orig_paragraphs = extract_content_paragraphs(original)
    pol_paragraphs = extract_content_paragraphs(polished)
    lost = orig_paragraphs - pol_paragraphs  # 用 sha256(normalize(text)) 做集合运算
    if lost:
        # 允许 5% 以内的"措辞调整"丢失；超出的视为内容被改写
        lost_chars = sum(len(p) for p in lost)
        orig_chars = sum(len(p) for p in orig_paragraphs)
        loss_ratio = lost_chars / orig_chars if orig_chars else 0
        if loss_ratio > 0.20:
            errors.append(("paragraph_modified", f"{loss_ratio:.1%} 内容被改写"))
    
    # 4. token 数下限（不是字符数，更准）
    orig_tokens = count_tokens(original)
    pol_tokens = count_tokens(polished)
    if pol_tokens < orig_tokens * 0.7:
        errors.append(("token_loss", f"输出 tokens {pol_tokens} 少于原文 70%"))
    
    # 5. 本章小结 section 必有
    if '## 本章小结' not in polished:
        errors.append(("missing_summary", "缺少本章小结 section"))
    
    return errors

def extract_content_paragraphs(md: str) -> set[str]:
    """提取 ### 下的段落（不含标题行），按句子级 normalize 后取 sha256"""
    hashes = set()
    for block in re.split(r'^### ', md, flags=re.MULTILINE):
        body = re.sub(r'^#+ .*\n', '', block, flags=re.MULTILINE).strip()
        for sentence in split_sentences(body):
            normalized = re.sub(r'\s+', '', sentence)  # 去除空白
            if len(normalized) > 10:  # 忽略短句
                hashes.add(sha256(normalized.encode()).hexdigest())
    return hashes
```

校验失败的章节：**自动重试 2 次**，仍失败的章节保留 Step 2 的原始聚合版本（不润色），并在 manifest 中标记 `"polished": false`。

---

## 六、Step 4：编译输出（修订：目录隔离）

### 6.1 输出目录（修订：与 KC book 分离）

```
<project_root>/book-wiki/                     ← 与既有 KC book/ 隔离
├── manifest.json
├── 00-目录.md
├── 卷一-写作基础/
│   ├── 01-选题与立意.md
│   ├── 02-大纲与结构.md
│   └── ...
├── 卷二-人物与情节/
├── ...
└── 卷七-综合参考/                            ← 必有（兜底卷）
```

**CLI 命令**：

```bash
python -m src.cli book build-from-wiki --project <id> --output-dir book-wiki --apply
```

`--output-dir` 默认 `book-wiki/`（与 KC book 的 `book/` 隔离开）。CLI 子命令 `book build-from-wiki` 与既有 `book build` 独立，避免参数冲突。

### 6.2 manifest.json

```json
{
  "book_title": "网文写作百科全书",
  "book_id": "book-wiki-{sha256(project_id + novel_wiki)[:12]}",
  "generated_at": 1788577597614,
  "source": "wiki",
  "source_filter": "concepts + entities + synthesis (sources excluded)",
  "total_pages": 1255,
  "assigned_pages": 1255,
  "total_chapters": 45,
  "total_volumes": 7,
  "volumes": [
    {
      "id": "v1",
      "title": "写作基础",
      "chapters": [
        {
          "id": "v1-ch01",
          "title": "选题与立意",
          "file": "卷一-写作基础/01-选题与立意.md",
          "page_count": 32,
          "wikilink_count": 32,
          "rendered_hash": "sha256...",
          "polished": true
        }
      ]
    }
  ],
  "taxonomy_source": "knowledge/novel-wiki/taxonomy.md",
  "wiki_root": "knowledge/novel-wiki/wiki/",
  "outline_source": "book-wiki/_outlines/final_outline.json"
}
```

### 6.3 全书目录 (00-目录.md) — 修订：含 overview

```markdown
# 网文写作百科全书 · 目录

> 生成时间：{generated_at} | 来源：knowledge/novel-wiki/wiki | 共 1255 条 / 45 章 / 7 卷

## 卷一：写作基础

本卷聚焦网文写作的基础流程与方法论，从选题到开篇的全链路。

1. **第1章 选题与立意** — [32 条](卷一-写作基础/01-选题与立意.md)
   > 本章涵盖网文选题的核心方法论，包括题材选择、市场定位、差异化策略等。

2. **第2章 大纲与结构** — [28 条](卷一-写作基础/02-大纲与结构.md)
   > 本章梳理大纲设计的多种方法（Snowflake Method、三幕式、起承转合）...

3. **第3章 开篇与黄金三章** — [25 条](卷一-写作基础/03-开篇与黄金三章.md)
   > ...

## 卷二：人物与情节
...

## 卷七：综合参考

本章汇集分类置信度较低或跨主题的页面，作为查询补充。

1. **第1章 平台术语速查** — [45 条]
2. **第2章 流派与桥段库** — [120 条]
```

---

## 七、成本估算（修订：实测 token 数）

实际 token 数需 Step 0 跑完后用 tokenizer 精算。下表是估算上限：

| 步骤 | 调用次数 | 单次输入 tokens | 单次输出 tokens | 总 tokens |
|---|---|---|---|---|
| Step 1.0 卷分配 | 1 | ~30k | ~5k | ~35k |
| Step 1.1~1.7 卷细化 | 6-8 | ~25k | ~8k | ~200k |
| Step 1 校验补全 | 0-3 | ~25k | ~8k | ~75k |
| Step 2 聚合 | 0 | — | — | 0 |
| Step 3 润色 | ~45 | ~8k | ~4k | ~540k |
| Step 3 校验重试 | 0-10 | ~8k | ~4k | ~120k |
| **合计上限** | **~70** | | | **~970k** |

> 较 v1 翻倍：单卷细化每次要带 ~30 个页面的 relations，token 比 v1 估算大；润色每章输入含桶分组结构而非线性 markdown 文本。

**预算上限**：
- 总调用 ≤ 70 次（超出则停止，输出当前进度让用户决定）
- 单章润色重试 ≤ 2 次（仍失败保留 Step 2 原始版）

---

## 八、已确定决策（原"待确认事项"的最终结论）

| 原 § | 决策 |
|---|---|
| 8.1 卷粒度 | **LLM 自由 6-10 卷**，含 1 个「综合参考」兜底卷 |
| 8.2 entities 处理 | **选项 C**：LLM 按 title + 写作价值判断 → 分散到相关章节 + 低置信度归兜底卷 |
| 8.3 sources 纳入 | **不纳入**（噪声大、74% 与 concepts 重叠）。未来如需，扩展 Step 2 处理 `page_type=source` |
| 8.4 无标签页面 | **选项 B + confidence 字段**：LLM 给每个无标签页 confidence，< 0.5 归兜底卷 |
| 8.5 输出格式 | **选项 C**：Markdown 为主 + manifest.json 结构化索引 |

---

## 九、实现计划（修订：模块路径与测试策略）

### Task 1：Step 0 准备工作
- 模块：`src/kc/views/book/wiki/scanner.py`
- 模块：`src/kc/views/book/wiki/taxonomy_stats.py`
- 测试：
  - `tests/test_kc/test_book_wiki_scanner.py` — 用真实 novel-wiki 数据 fixture 验证
  - `tests/test_kc/test_book_wiki_taxonomy_stats.py`
- 验收：`_pages.jsonl` 行数 = 1255，`_taxonomy_summary.txt` 主分类统计正确
- 预计：1h

### Task 2：Step 1 LLM 编排
- 模块：`src/kc/views/book/wiki/outline_llm.py`（所有 LLM 调用在 src/ 内，不放 scripts/）
- 模块：`src/kc/views/book/wiki/outline_validate.py`（覆盖校验 + 补全）
- 测试：
  - `tests/test_kc/test_book_outline_llm.py` — mock LLM 响应，验证 prompt 构造 + JSON 解析
  - `tests/test_kc/test_book_outline_validate.py` — 验证覆盖率校验 + 章节数阈值
- 验收：mock 测试通过；真实数据 dry-run 后能产出覆盖 1255 条的最终 outline.json
- 预计：3h

### Task 3：Step 2 规则聚合引擎
- 模块：`src/kc/views/book/wiki/parser.py`（WikiPage 数据类 + heading 归一化）
- 模块：`src/kc/views/book/wiki/aggregator.py`（按 heading 归桶 + 模糊匹配 + 兜底）
- 模块：`src/kc/views/book/wiki/markdown.py`（章节 Markdown 渲染）
- 测试：
  - `tests/test_kc/test_book_wiki_parser.py`
  - `tests/test_kc/test_book_wiki_aggregator.py` — 含模糊匹配、兜底桶、role 排序测试
  - `tests/test_kc/test_book_wiki_markdown.py`
- 验收：聚合后每章 markdown 含原页面的所有 section（包括模糊匹配和兜底桶）
- 预计：3h

### Task 4：Step 3 LLM 润色
- 模块：`src/kc/views/book/wiki/polish_llm.py`
- 模块：`src/kc/views/book/wiki/polish_validate.py`（含 5 项校验：wikilink、h3、段落哈希、token 数、小结 section）
- 测试：
  - `tests/test_kc/test_book_polish_llm.py` — mock LLM
  - `tests/test_kc/test_book_polish_validate.py` — 各校验项的失败用例
- 验收：mock 测试覆盖所有校验场景
- 预计：2h

### Task 5：Step 4 编译输出
- 模块：`src/kc/views/book/wiki/compiler.py`
- 模块：`src/kc/views/book/wiki/__init__.py`（公共 API）
- 测试：
  - `tests/test_kc/test_book_wiki_compiler.py` — 文件生成、目录结构、manifest 准确性
- 验收：dry-run 产出 1255/1255 完整分配 + manifest 各项字段正确
- 预计：2h

### Task 6：CLI 接入与端到端
- 修改：`src/cli_ext/book_cmd.py` — 新增 `book build-from-wiki` 子命令
- 修改：`src/cli_ext/llm_providers.py`（如需）— 确保从 .env 自动读取 provider
- 测试：
  - `tests/test_cli_ext/test_book_build_from_wiki.py` — CLI 参数解析、provider 加载
- 验收：
  - `python -m src.cli book build-from-wiki --project <id> --dry-run` 输出预期 JSON
  - `--apply` 后 `<project>/book-wiki/` 目录结构与 manifest 完整
- 预计：2h

### Task 7：试点验证（角色4建议）
- 选 1 章（如"选题与立意"，估 30 页）端到端跑通
- 人工评审产出质量
- 通过后再批量执行所有卷
- 验收：试点章节产物 < 角色4的「产出物应是结构化百科」验收标准
- 预计：2h

**总预计：15h**

---

## 十、风险与缓解（修订：补全遗漏条目）

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| LLM 输出结构不稳定（JSON 解析失败） | 高 | 高 | `response_format={"type": "json_object"}` 强制 + 解析失败自动重试 |
| LLM 输出 page_title 与真实 wiki 标题不一致 | 高 | 高 | 用 title 二次查表映射 wiki_id；查不到则该页丢弃 + 补全调用 |
| 单卷细化遗漏页面 | 中 | 高 | 自动二次调用补全；最多 2 次 |
| 单章润色内容丢失 | 中 | 高 | 段落哈希守恒 + token 数下限；失败保留原始版 |
| SECTION_MAP 漏匹配 | 中 | 中 | 模糊匹配 fallback + 「其他内容」兜底桶 |
| sources 未纳入导致溯源缺失 | 低 | 低 | 在 manifest 加 `source_filter` 字段说明；wiki/ 保留 sources 原页可点击跳转 |
| 25 个碎片子类归并 | 低 | 低 | 硬约束 7 强制 LLM 归并；校验阈值 1-5 章/卷 |
| book-wiki/ 目录已存在 | 低 | 中 | 写入前备份到 `book-wiki.bak.{timestamp}/` |
| LLM 调用超 70 次预算 | 低 | 中 | 达到上限时停止输出当前进度，让用户决定 |
| 408 个无标签分类质量差 | 高 | 中 | confidence < 0.5 归兜底卷（v7 综合参考） |
| 项目未 init 导致 CLI 失败 | 高 | 高 | §0.1 前置条件清单；执行前自检 |
| LLM provider 未配置 | 高 | 高 | §0.1 前置条件；执行前自检 |

---

## 十一、端到端验证清单

执行完成后，按下列清单逐项验证：

- [ ] Step 0：`_pages.jsonl` 行数 = 1255，`_taxonomy_summary.txt` 9 个分类完整
- [ ] Step 1：每个卷 outline 覆盖率 = 100%，章节数 15-50，overview 必有
- [ ] Step 1.0：兜底卷（v7）包含所有 confidence < 0.5 的页面
- [ ] Step 2：每章 markdown 含所有 section（精确匹配 + 模糊匹配 + 兜底桶）
- [ ] Step 2：无静默丢弃（"其他内容"桶非空时一定渲染）
- [ ] Step 3：润色后的章节通过 5 项校验
- [ ] Step 3：失败章节 manifest `polished: false`
- [ ] Step 4：`book-wiki/` 目录结构与 manifest 一致
- [ ] Step 4：manifest `total_pages = 1255 = assigned_pages`
- [ ] Step 4：00-目录.md 每章含 overview
- [ ] CLI：`book build-from-wiki --dry-run` 输出 JSON 报告
- [ ] CLI：`book build-from-wiki --apply` 后磁盘内容与 dry-run 一致

---

## 附录：v1 → v2 改动一览

| v1 | v2 | 原因 |
|---|---|---|
| 输出到 `<project>/book/` | 输出到 `<project>/book-wiki/` | 与 KC book 隔离 |
| CLI `book build --from-wiki` | CLI `book build-from-wiki` | 子命令独立，无参数冲突 |
| scripts/book_outline.py | src/kc/views/book/wiki/outline_llm.py | 模块私有约束 |
| 数据 1255 / 1718 混乱 | 统一 1255，sources 不纳入 | 口径统一 |
| taxonomy_summary.txt 假定存在 | Step 0 统计脚本生成 | 不假设中间产物 |
| project_id 用页面标题 | page_title + wiki_id 双键 | 避免 LLM 拼错系统 ID |
| Step 1：两批 + 汇总合并 | 按卷独立规划 + 自动补全 | 避免合并丢失 |
| 每章 15-50 vs 校验 10-60 | 校验阈值收紧为 10-60 提示 | 契约一致 |
| 408 无标签无置信度 | confidence 字段 + 兜底卷 | 兜底机制 |
| SECTION_MAP 精确匹配 | 模糊匹配 + 「其他内容」兜底 | 覆盖不全 |
| role 强制覆盖归类 | role 仅做排序权重 | 避免空内容 |
| 单 wikilink 集合校验 | 段落哈希 + token 数 + h3 + wikilink + 小结 5 项 | 内容守恒 |
| Step 4 写入无备份 | 写入前备份 book-wiki.bak.{ts} | 防止丢失 |
| 13h 估算 | 15h（含试点验证 Task 7） | 反映新增工作量 |
| 目录只有计数 | 目录含每章 overview | 增强导航 |
| book_id 静态 | book-wiki-{sha256[:12]} | 避免冲突 |
| LLM provider 假定有 | §0.1 前置条件清单 | 显式准备 |
| 测试策略缺失 | 每 Task 显式测试项 + mock | TDD 流程 |