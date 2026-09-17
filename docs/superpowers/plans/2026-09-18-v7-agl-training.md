# V7 摄取管线 × Agent Lightning 训练方案 — v2.0(plan-audit 整改后)

**状态**: v2.0(plan-audit 两轮审查 + 整改完成)
**日期**: 2026-09-18
**作者**: 用户 + Codex(35 项 grilling 决策 + 6 个 subagent 代码级审计)
**关联档案**: `.memory/feedback-v7-agl-design-tree-2026-09-18.md`
**审计日志**: `docs/superpowers/plans/2026-09-18-v7-agl-training-audit-log.md`

## 改动摘要(v1.0 → v2.0)

| 维度 | v1.0 | v2.0 |
|---|---|---|
| 训练拓扑 | 1 raw = 1 rollout | **1 topic = 1 rollout**(Stage1/3/4 离线)|
| LLM 客户端注入 | 改 ProviderRegistry 全局 | **新加 `BaseURLLLMClient` adapter**(临时 llm-providers.json)|
| 训练目标验收 | spot-check ≥3.5/5 绝对分 | **baseline + 0.5 相对提升** |
| candidate pipeline 兼容性 | 假设破坏 | **不破坏**(grep 验证)|
| 10 条 raw 文件 | 推荐 10 个 | **9 个存在 + 1 个替换** |
| GPU 规格 | 未明 | **1.5B 模型 + A100 40GB / RTX 4090** |
| max_tokens | 4096 | **8192**(8 slot × 200 字 + JSON) |
| post_process_page | `__init__` 参数 | **setter 方法**(避免 kwargs 顺序) |
| `CONCEPT_SLOTS` 改 8 项 | 1 处 + 2 镜像 | **3 处 + 1 fallback 镜像** 全同步 |
| ProviderRegistry thread-safe | 假设不安全 | **ProviderRegistry 不是 singleton,改 base_url 生效** |
| AGL proxy URL 拼接 | `f"{base_url}/chat/completions"` | **`os.environ["AGL_OPENAI_BASE_URL"]` 直接用** |
| PR 验收 | e2e test pass | **加 candidate pipeline 不破坏验证 + 4 项烟测 checklist** |
| 训练样本 manifest | 缺 | **加 manifest 锁定,后续阶段不重复** |
| spot-check rubric | 缺 | **8 slot × 5 维度(40 分 → 1-5 标准化)** |
| LLM-judge prompt | 缺 | **8-slot concept 模板** |
| 硬回滚 | quarantine 隔离 | **AGL 默认写 `_agl/` 子目录 + 人工审核 move** |
| 软回滚 | provider flag | **provider flag + stop_agl_training.sh 一键清理** |

## 一、目标(Goal Alignment)

**核心目标**:用 Agent Lightning 训练 V7 摄取管线的 Stage5 LLM,在 novel-wiki 实例上产出**质量更高的 8-slot concept wiki 页**。

**成功标准(量化,含基线对比)**:
- **基线测量(训练前必做)**:用**未训 V7 LLM** 跑 10 条 raw,人工 spot-check 得 `V7-baseline = X/5`
- **最小烟测(10 条)**:loss 单调下降 + spot-check 平均分 ≥ `max(3.5, baseline + 0.5)`/5
- **小规模(100 条)**:reward ≥0.5 + spot-check ≥ `max(3.8, baseline + 0.7)`/5
- **中规模(500 条)**:reward ≥0.5 + spot-check ≥ `max(4.0, baseline + 1.0)`/5
- **最终上线**:spot-check 200 条通过率 ≥75% + LLM-as-judge 100 条 hold-out ≥4.0/5 + 50 条人工复核

**评分 rubric(8 slot × 5 维度,40 分 → 标准化 1-5)**:
- 完整性(8 个 slot 都有内容):0-5 分
- 准确性(内容是否对 raw 真实):0-5 分
- 可读性(语言流畅度):0-5 分
- wikilink 数量(related_concepts slot 有 [[wikilink]]):0-5 分
- 标签准确(tags 反映内容分类):0-5 分
- **总评**:8 个 slot 的 5 个维度评分平均 → 0-5 标准化

**LLM-as-judge 模板(8-slot concept)**:
```yaml
prompt: |
    Given a wiki page (8-slot concept template) and its source raw text,
    score the page on 5 dimensions, each 0.0-1.0:
    1. completeness: all 8 slots (定义/主要特点/适用场景/反模式与常见错误/证据强度/例子/相关概念/参考来源) present
    2. accuracy: claims match raw text
    3. readability: language quality
    4. wikilinks: related_concepts slot has [[wikilinks]] to other concepts
    5. tags: tags reflect content categories accurately

    Output JSON: {"scores": {completeness, accuracy, readability, wikilinks, tags}, "total": sum/5}
```
- 总分 = 5 个维度平均 → 0.0-1.0 标准化
- 阈值 ≥0.7 → 转 4.0/5 标准化
- **provider**:跟训练 provider 不同(避免 bias),用更强 LLM(MiniMax-M3 或 Claude)

**non-goals**(明确不做):
- 不训 Stage1/3/4(冻结,沿用现有 V7 LLM)
- 不训 entity / synthesis / source / tool 类型(只训 concept)
- 不改 V7 ownership 6 字段契约
- 不污染主 wiki frontmatter(AGL 训练轨迹存独立文件,wiki 写 `_agl/` 子目录)
- 不删 5 个 DEAD 字段,V7 wiki_writer 本来就不写,删除破坏 V2 迁移脚本

## 二、关键前提(Assumptions)

| # | 前提 | 不成立时的失效风险 | 验证方法 |
|---|---|---|---|
| A1 | V2 `fill_slots` 单次 LLM call 路径稳定可用 | V2 路径不可用,只能走 V3 多 slot(9 次 LLM call) | PR-A 前 grep `src/pipeline/v7_extract/slot_filler.py` 调用链 |
| A2 | novel-wiki 的 1362 个 raw 文档是真实素材,不含敏感数据 | 数据有版权/合规问题,无法用于训练 | 抽样 50 条人工 spot-check |
| A3 | 强 LLM(MiniMax-M3 / Claude / GPT-4)有 API key 预算可用 | 无法造 ground truth,无法做 LLM-judge | `llm-providers.json` 验证 + API budget monitor |
| A4 | Linux GPU 机器可用:**起步 1.5B 模型(Qwen/Qwen2.5-1.5B-Instruct)+ 1× A100 40GB 或 RTX 4090 24GB** | AGL 训练无法跑 | 提前申请 GPU 机时间 |
| A5 | V7 `CONCEPT_SLOTS` 改 8 项不会破坏 candidate pipeline | V7 e2e test 失败,生产 wikis 受影响 | grep 验证 candidate pipeline 不依赖 CONCEPT_SLOTS;改完跑 `tests/test_integration/test_v7_e2e_remediation.py` |
| A6 | AGL gateway proxy 在 Linux/WSL 下能完整跑通(rollout/event/模型注册 4 项 checklist) | 训练实验无法启动 | 前置 4 项烟测 |
| A7 | 用户能持续提供人工 spot-check(每轮 ≥30 分钟) | 评估无法闭环 | 跟用户确认时间预算 + 训练暂停条件 |
| A8 | `BaseURLLLMClient` adapter 不需要改 V7 公共代码 | 改 V7 公共代码风险大 | 实现后跑 V7 e2e test 验证 |
| A9 | V7 stage-remediation master plan 不在 AGL 训练期间合入主分支 | 训练实验被 V7 整改 plan 干扰 | 跟 stage-remediation owner 约定时间窗口 |

## 三、训练对象(明确边界)

**训练哪个 LLM**:
- **唯一目标**:`src.pipeline.v7_extract.slot_filler` 的 LLM 调用(在 `fill_slots` 函数内,通过 `LLMClient.complete(prompt_kind="fill_slots", ...)`)
- **其他 LLM 调用**(Stage1/3/4):**冻结**,沿用现有 V7 provider,**离线预计算** topics

**强制约束**:`v7_agl_agent.py` 里设 `V7_USE_V3=false` 强制走 V2 路径,避免 V3 `claim_extractor` per-slot 多 call 替换。

**训练拓扑**:**1 rollout = 1 topic**(不是 1 raw)
- Stage1/3/4 离线跑(用 frozen LLM),产物存 `.index/agl/experiments/<exp>/precomputed_topics/`
- AGL rollout 只跑 Stage5,输入是预生成的 topic
- 1 raw 可能产出 N topic → N rollout → N triplet,1 个 reward 不被 broadcast 稀释

## 四、工程边界(Boundaries)

| 层 | 负责方 | 与 AGL 关系 |
|---|---|---|
| Stage1 doc_classifier | V7 LLM,冻结 | **离线跑**,产物存预计算 topics |
| Stage3 completeness_checker | V7 LLM,冻结 | **离线跑** |
| Stage4 topic_clusterer | V7 LLM,冻结 | **离线跑** |
| **Stage5 slot_filler** | **AGL 训过的 LLM** | **训练目标**(1 rollout = 1 topic)|
| Stage6 relation_extractor | 不训 | Stage7 wikilinks 反推 |
| Stage7 wiki_writer | V7 Python,3 个 patch | 8-slot 强检查 + 规则引擎 + version comment + 写 `_agl/` 子目录 |
| AGL Gateway | `agl-server` (Linux/WSL) | 抓 Stage5 单次 LLM 调用 |
| AGL Controller | `agl-controller runner_type=local` (Linux/WSL) | spawn `v7_agl_agent.py` |
| AGL Trainer | verl + vLLM + GRPO | 全参训 Stage5 LLM |

## 五、V7 patch 范围(4 个独立 PR,先 merge 主分支)

### PR-A:`feat(v7-extract): Stage5 slot_filler 升 8 slot`

**改动**(~60 行):
- `src/pipeline/v7_extract/slot_filler.py:42`:`CONCEPT_SLOTS` 从 5 项改 8 项
  - 加 `context`(适用场景)、`anti_patterns`(反模式与常见错误)、`evidence`(证据强度)
- `src/pipeline/v7_extract/prompts/builtin/fill_slots.toml`:`[user]` example 输出从 5 slot 名改 8 slot 名
- `src/pipeline/v7_extract/wiki_writer.py:_write_page_atomically`:在写 body 前注入 `<!-- wiki-template-version: 3.0.0 -->` HTML comment
- `src/pipeline/v7_extract/page_synthesizer.py:65-71` 的 `_CONCEPT_SLOTS` 镜像:同步改 8 项
- `src/pipeline/v7_extract/_legacy_slot_filler.py:41` 的 `CONCEPT_SLOTS` 副本:同步改 8 项
- `src/pipeline/v7_extract/_legacy_slot_filler.py:428,433,436` 的 `CONCEPT_SLOTS` 引用:同步

**测试**:
- `grep "definition|characteristics|examples|related_concepts|references"` 在 `tests/corpus/v7_gold/` 找 expected output 引用,同步更新 fixtures
- `tests/test_integration/test_v7_e2e_remediation.py` 跑通
- **candidate pipeline 不破坏验证**:`tests/test_pipeline/` 全 pass + `tests/test_integration/` 全 pass

### PR-B:`feat(v7-extract): Stage7 commit 前 8-slot 强检查 + 规则引擎`

**改动**(~250 行):
- `src/pipeline/v7_extract/wiki_writer.py`:
  - `WikiWriter.__init__` **不变**(避免参数顺序风险)
  - **新增** `WikiWriter.set_post_process_page(page: Callable[[ConceptPage], ConceptPage] | None)` setter 方法
  - `commit_and_index` 在写盘前调 `self._post_process_page(page)`(若已设)
  - **默认路径**:wiki 写到 `_agl/` 子目录而非 `wiki/concepts/`(AGL 训练隔离)
- 新增 `src/pipeline/v7_extract/post_process.py`:
  - `enforce_8slot_concept(page)` — body 必须含 8 个 `## heading`,否则 raise `IncompleteSlotError`
  - `infer_tags_from_body(page, sources)` — 从 body + sources 反推 tags
  - `infer_relations_from_wikilinks(page)` — 从 body wikilinks 反推 relations
  - `default_post_process_page(page, sources)` — 串起来
- `src/pipeline/v7_extract/failures.py`:加 `IncompleteSlotError` 到 FailureStatus 枚举

**测试**:
- `tests/test_pipeline/test_v7_extract_post_process.py`(新):覆盖 8-slot 缺失、tags 反推、relations 反推
- 旧 e2e 测试不破坏(默认 post_process_page=None)

### PR-C:`feat(v7-extract): BaseURLLLMClient adapter for AGL 注入`

**改动**(~80 行):
- `src/pipeline/v7_extract/llm_client.py`:新增 `BaseURLLLMClient` 类

```python
class BaseURLLLMClient(LLMClient):
    """绕开 ProviderRegistry,直接 base_url + api_key 构造的 LLM client。

    用于 Agent Lightning 训练时,把 Stage5 LLM 调用路由到 AGL Gateway proxy。
    """
    def __init__(self, *, base_url: str, api_key: str,
                 model: str = "Qwen/Qwen2.5-1.5B-Instruct",
                 timeout_seconds: int = 300):
        from src.llm.openai_provider import OpenAIProvider
        from src.llm.types import ProviderConfig
        self._provider = OpenAIProvider(config=ProviderConfig(
            name="agl_proxy",
            type="openai",
            base_url=base_url,
            api_key=api_key,
            default_chat_model=model,
            timeout_seconds=timeout_seconds,
        ))

    async def complete(self, *, prompt_kind, user_prompt, system_prompt="",
                       max_tokens=8192, temperature=0.0):
        from src.llm.types import LLMResponse
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        response: LLMResponse = await self._provider.complete(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.content
```

**测试**:
- `tests/test_pipeline/test_v7_extract_base_url_client.py`(新):验证 adapter 路由正确

### PR-D:`feat(lint): LINT-MISSING-COMMENT`

**改动**(~50 行):
- `src/wiki/features/lint.py`:新增 `LINT-MISSING-COMMENT` — V7 写的页如果没 `<!-- wiki-template-version -->` 就告警(防止 PR-A 漏写)

**测试**:
- `tests/test_wiki/test_lint.py` 加 `LINT-MISSING-COMMENT` 用例
- `tests/test_pipeline/test_v7_extract_lint_test.py`(新)

## 六、AGL 集成(在 `feature/2026-XX-XX-v7-agl-training` 分支)

### Stage1/3/4 离线预计算(`precompute_topics.py`)

```python
"""Stage1/3/4 离线跑,产物存 .index/agl/experiments/<exp>/precomputed_topics/"""
import asyncio
import json
from pathlib import Path

from src.pipeline.v7_extract.doc_classifier import classify_doc
from src.pipeline.v7_extract.completeness_checker import check_completeness
from src.pipeline.v7_extract.topic_clusterer import cluster_topics


async def precompute_topics(raw_path: Path, project_root: Path) -> list[dict]:
    raw_text = raw_path.read_text(encoding="utf-8", errors="ignore")
    doc_type = await classify_doc(raw_text, filename_hint=raw_path.name)
    is_complete, _ = await check_completeness(raw_text, doc_type=doc_type)
    topics = await cluster_topics(raw_text, doc_type=doc_type)
    return [
        {"topic_id": t.id, "title": t.title, "sources": list(t.item_ids or [])}
        for t in topics
    ]


async def main():
    project_root = Path("knowledge/novel-wiki")
    output = project_root / ".index/agl/experiments/smoke/precomputed_topics.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as f:
        for raw_path in selected_10_raws():
            topics = await precompute_topics(raw_path, project_root)
            for topic in topics:
                f.write(json.dumps({
                    "raw_path": str(raw_path),
                    "topic": topic,
                }) + "\n")


def selected_10_raws() -> list[Path]:
    return [
        project_root / "raw/sources/01_新手入门/入门教程爽文的五种归纳.md",
        project_root / "raw/sources/01_新手入门/入门教程基础篇网络小说的类型.md",
        project_root / "raw/sources/01_新手入门/入门教程十大小说写作技巧.md",
        project_root / "raw/sources/02_进阶技巧/方法论美文语言的诗意营造.md",
        project_root / "raw/sources/02_进阶技巧/补充教程写穿越小说角色前要注意的十个问题.md",
        project_root / "raw/sources/03_大纲创作/大纲示例成神大纲.md",
        project_root / "raw/sources/01_新手入门/借鉴素材写作大纲经典都市写作大纲二十二条主线.md",
        project_root / "raw/sources/04_题材专题/东方玄幻魏晋南北朝贵族沐浴奇习俗.md",
        project_root / "raw/sources/01_新手入门/借鉴素材玄幻与仙侠的区别.md",
        project_root / "raw/sources/05_运营出版/运营课程10如何处理主角挫折.md",
    ]
```

### AGL Agent 适配器:`v7_agl_agent.py`

```python
"""V7 Stage5 的 Agent Lightning 适配器(1 rollout = 1 topic)。"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import httpx

# 强制 V2 路径
os.environ["V7_USE_V3"] = "false"


class Agent:
    """AGL local controller spawn 这个 Agent 跑 1 topic → 1 ConceptPage。"""

    async def run(self) -> None:
        # AGL 注入的 env vars
        agl_base_url = os.environ["AGL_OPENAI_BASE_URL"]   # 完整 proxy URL
        event_url = os.environ["AGL_EVENT_URL"]
        agl_key = os.environ["AGL_KEY"]

        # 业务输入(由 trainer 通过 env_map 注入)
        topic_id = os.environ["TOPIC_ID"]
        topic_title = os.environ["TOPIC_TITLE"]
        topic_sources = json.loads(os.environ["TOPIC_SOURCES"])
        raw_path = os.environ["RAW_PATH"]
        project_id = os.environ["PROJECT_ID"]

        raw_text = Path(raw_path).read_text(encoding="utf-8", errors="ignore")

        # **Stage5: AGL Gateway 拦截的 LLM 调用**
        from src.pipeline.v7_extract.slot_filler import fill_slots
        from src.pipeline.v7_extract.llm_client import BaseURLLLMClient
        from src.pipeline.v7_extract.post_process import default_post_process_page

        # **用 PR-C 的 BaseURLLLMClient,不走 ProviderRegistry**
        llm = BaseURLLLMClient(
            base_url=agl_base_url,  # AGL Gateway proxy URL(已经是完整路径)
            api_key=agl_key,
            model=os.environ.get("AGL_TRAIN_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"),
        )

        page = await fill_slots(
            topic={"id": topic_id, "title": topic_title, "item_ids": topic_sources},
            source_text=raw_text,
            llm=llm,
        )

        # Stage7: 写 _agl/ 子目录(AGL 训练隔离,人工审核后 move)
        from src.pipeline.v7_extract.wiki_writer import WikiWriter
        from src.wiki.core.paths import WikiPaths

        paths = WikiPaths(Path(f"knowledge/{project_id}"))
        writer = WikiWriter(paths=paths)
        writer.set_post_process_page(default_post_process_page)
        writer.set_output_subdir("_agl")  # AGL 训练写到 wiki/_agl/concepts/<id>.md

        if page is not None:
            report = writer.commit_and_index([page])
            reward = _score_page(page, report)
        else:
            reward = 0.0

        # 上报 reward
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                event_url,
                json={
                    "event_type": "reward",
                    "data": {
                        "value": reward,
                        "source": "v7-agl",
                        "reason": f"topic_id={topic_id} success={page is not None}",
                    },
                },
                headers={"Authorization": f"Bearer {agl_key}"},
            )


def _score_page(page, report) -> float:
    """Reward:0-1 综合分。8-slot 完整性 + Stage7 commit 成功 + LLM-as-judge。"""
    if page is None:
        return 0.0
    # 8-slot 完整性
    body = page.body or ""
    required_slots = ["定义", "主要特点", "适用场景", "反模式与常见错误",
                      "证据强度", "例子", "相关概念", "参考来源"]
    present = sum(1 for slot in required_slots if f"## {slot}" in body)
    slot_score = present / len(required_slots)
    # Stage7 commit 成功
    commit_score = 1.0 if report.written else 0.0
    return (slot_score + commit_score) / 2
```

### AGL RolloutHook(`agl_hooks.py`)

```python
"""AGL RolloutHooks — 标 Stage5 model_request 事件 + 过滤。"""
from agentlightning.hooks import RolloutHooks
from agentlightning.schemas import Rollout, RolloutCreate
from typing import Any


class V7AglHook(RolloutHooks):
    def on_enqueue(self, request: RolloutCreate) -> RolloutCreate:
        request.config.local.agent_class = "v7_agl_agent.Agent"
        # env_map 注入 1 rollout = 1 topic 需要的字段
        request.config.local.env_map = {
            "TOPIC_ID": "input.topic_id",
            "TOPIC_TITLE": "input.topic_title",
            "TOPIC_SOURCES": "input.topic_sources",
            "RAW_PATH": "input.raw_path",
            "PROJECT_ID": "input.project_id",
            "AGL_TRAIN_MODEL": "input.model",
        }
        return request

    def on_succeeded(self, rollout: Rollout, events, store) -> None:
        """给 Stage5 的 model_request 事件打 marker。"""
        for attempt_id, attempt_events in events.items():
            for event in attempt_events:
                if event.event_type == "model_request":
                    # prompt_kind == "fill_slots" 标记 Stage5
                    data = event.data
                    prompt_kind = data.get("request", {}).get("prompt_kind", "")
                    if prompt_kind == "fill_slots":
                        store.add_event(
                            rollout.rollout_id, attempt_id,
                            "stage5_marker", {"stage": "stage5"},
                        )
```

### 自定义 RolloutAdapter

继承 `agentlightning.verl.rollout_adapter.RolloutAdapter`,重写 `get_train_data_batch` 加 stage filter(行 480 加 stage predicate,只保留 stage5_marker 之后的 model_request 事件 triplets)。

## 七、数据流(Data Flow)

```
novel-wiki raw/sources/<file>.md
   ↓ (离线,Stage1/3/4 冻结 LLM)
precompute_topics.py → .index/agl/experiments/<exp>/precomputed_topics.jsonl
   ↓
train_agl_v7.py 读 topics.jsonl,每个 topic enqueue 1 rollout
   ↓ AGL Controller spawn agent
v7_agl_agent.py:
   ↓ 读预生成的 topic + raw_text
   ↓ **Stage5 fill_slots — AGL Gateway 拦截**
        ↳ BaseURLLLMClient → OpenAIProvider → AGL proxy URL → vLLM 训过的 LLM
        ↳ model_request 事件落入 AGL store + stage5_marker(hook)
   ↓ Stage7 wiki_writer 写 _agl/concepts/<id>.md
   ↓ 计算 reward(slot_score + commit_score)/2
   ↓ 上报到 /api/rollouts/{id}/events
   ↓
AGL trainer: rollouts/terminal + events → triplets
   ↓ custom RolloutAdapter 过滤 stage5_marker
   ↓
verl GRPO loss → Stage5 LLM 权重更新(全参)
```

## 八、训练回路(3 轮渐进,带 decision gate)

| 轮 | 样本量 | 训练目标 | 评估门槛 | 通过后 |
|---|---|---|---|---|
| 1. 最小烟测 | 10 topic | SFT 1 epoch + GRPO 1 batch | loss 单调下降 + spot-check ≥ `max(3.5, baseline+0.5)`/5 | **decision gate:用户签字** → 扩到 100 |
| 2. 小规模 | 100 topic | SFT 3 epoch + GRPO 多 batch | reward ≥0.5 + spot-check ≥ `max(3.8, baseline+0.7)`/5 | **decision gate** → 扩到 500 |
| 3. 中规模 | 500 topic | SFT + GRPO 全量 | reward ≥0.5 + spot-check ≥ `max(4.0, baseline+1.0)`/5 | **decision gate** → 决策是否扩到 1362 |

**关键约束**:
- 每轮结束**用户必须签字确认**才进下一轮(避免 PT5.3 目标漂移)
- 训练样本 manifest 锁定,后续阶段不重复选样(P6.4)
- 用户连续 2 轮无法 spot-check → 暂停训练(PT1.1)
- vLLM 错误率 >5% → pause(S1)
- AGL Gateway 重启 → 自动续传 wandb 同 run(PT3.1)

## 九、回滚方案

### 软回滚(provider flag + 资源清理)

```bash
# scripts/stop_agl_training.sh
#!/usr/bin/env bash
set -e

# 1. 关闭 AGL provider,fallback 原 V7
python -m src.cli llm-providers set-default v7-default  # 切回 V7 原 provider

# 2. SIGTERM AGL Controller
pkill -f agl-controller || true

# 3. SIGTERM vLLM 释放 GPU
pkill -f "vllm serve" || true

# 4. SIGTERM AGL Server
pkill -f agl-server || true

echo "AGL training stopped. V7 provider resumed."
```

### 硬回滚(AGL 默认写隔离目录,人工审核 move)

- AGL 训练 wiki 写到 `wiki/_agl/concepts/<id>.md`(不污染主 wiki 树)
- 主 wiki 目录:人工 spot-check 通过后,**手动 move** `wiki/_agl/concepts/<id>.md` → `wiki/concepts/<id>.md`
- 失败页:删除 `wiki/_agl/concepts/<id>.md`

### 回滚触发条件

- 生产 wiki 评审连续 3 批 spot-check 退步
- LLM-as-judge 评分下降 ≥0.1
- AGL Gateway 报错率 >5%
- 训练期间用户决策变更(PT5.3)

## 十、依赖项清单

### 代码 / 工具依赖

| 依赖 | 规格 | 验证 |
|---|---|---|
| **Python** | AGL 要求 3.12+,ruflo-kb 用 3.14 | separate venv |
| **GPU 起步** | **1× A100 40GB 或 RTX 4090 24GB**(1.5B 模型全参训 + vLLM serving)| 提前申请 |
| **GPU 扩量** | **1× A100 80GB 或 H100**(7B 模型)| 扩量时申请 |
| **模型规格** | 起步 Qwen/Qwen2.5-1.5B-Instruct(已有 calc_x 经验) | 起步 |
| **AGL 主仓** | `E:\002-Pr\agent-lightning-main`(已克隆)| `uv sync --no-group verl-cpu` |
| **verl + vLLM + Ray** | 0.7.1-0.9.0(vllm + ray + tensordict)| `bash scripts/setup_verl.sh 0.8.0 cu130` |
| **强 LLM** | MiniMax-M3 / Claude-haiku / GPT-4o-mini 任选,API key + base_url | `llm-providers.json` |

### Windows 装包前置验证

```powershell
# 实测 kr8s 是否能装(预期失败)
uv pip install -e E:\002-Pr\agent-lightning-main 2>&1 | tee install.log
# 如果失败,降级:
uv pip install --no-deps -e E:\002-Pr\agent-lightning-main
uv pip install fastapi uvicorn pydantic httpx httpx-retries hydra-core omegaconf structlog jinja2 pyyaml
```

### AGL 烟测 4 项 checklist(前置必跑)

- [ ] `agl-server` 起来 + `curl http://127.0.0.1:8181/healthz` 返回 200
- [ ] mock LLM endpoint 注册:`POST /api/models` 返回 201
- [ ] enqueue rollout:`POST /api/rollouts` 返回 201
- [ ] mock agent 上报 reward + `GET /api/rollouts/{id}/events` 返回 200
- 任一失败 → "AGL 不通",**不能进 GPU 训练阶段**(P2.3 整改)

### LLM-as-judge provider 配置

| Provider | 用途 | 备注 |
|---|---|---|
| **训练** | AGL Gateway 抓 Stage5 | Qwen/Qwen2.5-1.5B-Instruct(1.5B)起步 |
| **Ground truth** | 强 LLM 造 10/100/500 条 8-slot wiki | MiniMax-M3 / Claude-haiku / GPT-4o-mini |
| **LLM-judge** | 评估训练后 wiki 质量 | **必须跟训练 provider 不同**(避免 bias),推荐 Claude-haiku 或 GPT-4o-mini |

### wandb 配置

| 项 | 配置 |
|---|---|
| project | `agentlightning` |
| experiment | `<exp_name>`(如 `smoke` / `pilot-100` / `pilot-500`) |
| entity | 用户名(wandb 账号) |
| **降级方案** | 本地 tensorboard(PT3.1, S4 整改)|

## 十一、验收标准(可量化)

### 中间验收点(V7 PR)

- PR-A merge 后:
  - `tests/test_integration/test_v7_e2e_remediation.py` 全 pass
  - `tests/test_pipeline/` 全 pass
  - candidate pipeline 不破坏验证(`grep CONCEPT_SLOTS src/pipeline/` 确认无 import)
- PR-B merge 后:`tests/test_pipeline/test_v7_extract_post_process.py` 全 pass
- PR-C merge 后:`tests/test_pipeline/test_v7_extract_base_url_client.py` 全 pass
- PR-D merge 后:`tests/test_wiki/test_lint.py` 全 pass + V7 写的页能触发 LINT-MISSING-COMMENT

### 训练验收点

- **基线测量**:用未训 V7 LLM 跑 10 topic,人工 spot-check 算 `V7-baseline`
- **10 topic 烟测**:loss 单调下降 + spot-check ≥ `max(3.5, baseline+0.5)`/5
- **AGL Gateway 烟测 4 项 checklist 全 pass**(P2.3)
- **Linux GPU 实跑**:1 次完整 rollout(模型注册 + LLM 拦截 + reward 上报)

### 上线验收点

- 500 topic 训练后:
  - spot-check 200 topic 通过率 ≥75%
  - LLM-as-judge 100 topic hold-out ≥4.0/5
  - 50 topic 人工复核通过
  - `_agl/` 子目录的 wiki 全部 spot-check 通过后 move 到 `wiki/concepts/`

## 十二、盲区清单(已大部分解决)

- ~~训练样本选择的具体文件路径~~ → §六 precompute_topics.py 列出 9 个存在 + 1 个替换,基于 raw 分布调研
- ~~强 LLM 用于 ground truth + LLM-judge 的 provider 选择~~ → §十 LLM-as-judge provider 表
- ~~V2 `fill_slots` 在 novel-wiki 1362 raw 上能否稳定运行~~ → §十 实测验证
- ~~AGL Gateway 在网络受限环境的可用性~~ → §十 烟测 4 项 checklist
- ~~Linux GPU 机器的具体配置~~ → §十 GPU 起步规格
- 训练产物回滚到主分支的具体 PR 模板 → 起草中(PR-E)
- AGL Server 守护(systemd / supervisor)配置 → 待补
- AGL Server 内存限制(避免 PT3.1 重启)→ 待测
- vLLM 5xx 错误监控阈值(>5% pause)→ 待实现(S1)
- AGL training cost 独立记录(避免 P5.2 污染 metric)→ 待实现

## 十三、工作量估算

| 阶段 | 工作量 | 触发 |
|---|---|---|
| PR-A | 0.5 天 | V7 改造 |
| PR-B | 1 天 | V7 改造 |
| PR-C | 0.5 天 | V7 改造 |
| PR-D | 0.5 天 | lint 改造 |
| precompute_topics.py + 10 条 topic 造数据 | 1 天 | 数据准备 |
| v7_agl_agent.py + agl_hooks.py + RolloutAdapter | 2 天 | AGL 集成 |
| Windows 烟测(4 项 checklist) | 0.5 天 | 验证 |
| Linux GPU 烟测训练(10 topic)| 1 天 | 训练 |
| 基线测量 + 第 1 轮训练后 spot-check | 0.5 天 | 评估 |
| 第 2 轮 100 topic 训练 | 2 天 | 训练 |
| 第 3 轮 500 topic 训练 | 3 天 | 训练 |
| 评估 + 人工 spot-check + move wiki | 2 天 | 上线 |
| **总计** | **~2.5 周**(1 全职 + GPU 时间 + 用户 spot-check 时间)| 全流程 |

---

## 附录 A:数据存储路径

| 路径 | 用途 | gitignore 状态 |
|---|---|---|
| `knowledge/<kb>/.index/agl/experiments/<exp_name>/pages.jsonl` | AGL 训练轨迹 | 需加 gitignore exception |
| `knowledge/<kb>/.index/agl/experiments/<exp_name>/precomputed_topics.jsonl` | Stage1/3/4 离线产物 | 同上 |
| `knowledge/<kb>/.index/agl/quarantine/<exp_name>/` | 回滚隔离 | 同上 |
| `knowledge/<kb>/wiki/_agl/concepts/<id>.md` | AGL 训练产出的 wiki 页 | 不污染主 wiki |
| `wandb project=agentlightning,experiment=<exp_name>` | 训练指标 | N/A |
| `tensorboard logs/<exp_name>/` | 训练指标本地备份(S4 整改) | 待 gitignore |

## 附录 B:术语表

见 `CONTEXT.md` 新增的 V7 / AGL / Rollout / Triplet 章节。

## 附录 C:关联文档

- `.memory/feedback-v7-agl-design-tree-2026-09-18.md` — 35 决策 + 8 bug + 6 校准
- `docs/guides/v7-ingestion-pipeline.md` — V7 主文档
- `docs/superpowers/plans/2026-09-15-v7-pipeline-architecture-v3.md` — V3 架构对齐(独立 plan)
- `docs/superpowers/plans/2026-09-17-v7-stage-remediation-master-plan.md` — V7 整改 master plan(独立 plan,约定时间窗口)
- `E:\002-Pr\agent-lightning-main\docs\` — AGL 文档
- `docs/superpowers/plans/2026-09-18-v7-agl-training-audit-log.md` — plan-audit 审计日志