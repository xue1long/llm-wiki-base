# 批量摄取压力测试 - 第4轮优化方案（实际摄取验证）

**测试时间**: 2026-08-03 19:10
**测试方式**: 通过队列恢复API触发实际摄取
**状态**: 摄取成功完成，发现质量问题

---

## 发现的问题

### P1 - 页面内容槽位未填充

**现象**:
- 所有生成的wiki页面的body槽位都是"（待补充）"
- 例如：`## 摘要\n\n（待补充）`
- frontmatter正确生成（id, title, type, tags, relations等）

**示例**:
```markdown
## 来源元数据

（待补充）

## 摘要

（待补充）

## 关键观点

（待补充）
```

**根因分析**:
1. **生成器模式**: 可能是设计如此——Generator只生成frontmatter，body由后续流程填充
2. **LLM超时**: 可能在body生成阶段超时，但任务仍标记为approved
3. **模板残留**: 可能使用了占位模板，但填充逻辑未执行

**需要确认**:
- 检查Generator是否应该生成body内容
- 检查是否有"polish"流程补充body

---

### P2 - 标签验证导致任务卡住

**现象**:
- 1个任务因标签验证问题卡在running状态
- 错误信息：`missing mandatory tags: ['素材/ugc', '可信度/ugc']`
- 另一个任务：`invalid tag values: ['功能/素材']`

**影响**:
- 标签验证过于严格，可能阻止有效内容的摄取
- UGC标签应该是可选的，不应阻止摄取

---

### P3 - 摄取延迟很高（~60秒）

**现象**:
- 从入队到完成需要约60秒
- 单个文档处理链路长

**延迟分析**:
```
入队 → advance调度 → collector读取 → analyzer分析 → generator生成 → writer写入
      ↑ ~5s           ↑ ~10s            ↑ ~30s            ↑ ~10s
```

**瓶颈**:
- Analyzer阶段调用LLM，可能需要30秒
- 没有并行处理多个任务

---

## 优化方案

### 方案 A: Body内容生成流程修复

**目标**: 确保页面body槽位被正确填充

**实施步骤**:

1. **检查生成器配置**
   ```python
   # src/pipeline/generator.py
   # 确认 generate_from_knowledge_object 是否应该填充body
   ```

2. **添加polish后处理**
   ```python
   # 摄取完成后触发polish
   @event_bus.on("task:approved")
   async def polish_new_page(payload):
       # 使用LLM补充body内容
       await polish_wiki_page(payload.page_id)
   ```

3. **验证测试**
   ```python
   def test_generated_page_has_body():
       assert "（待补充）" not in page.body
   ```

---

### 方案 B: 标签验证宽松化

**目标**: 减少因标签问题导致的摄取失败

**实施步骤**:

1. **将UGC标签改为可选**
   ```python
   # src/wiki/features/tag_namespace.py
   MANDATORY_TAGS = []  # 移除 素材/ugc, 可信度/ugc
   ```

2. **添加默认标签推断**
   ```python
   # 如果缺少必需标签，根据内容类型推断
   if not has_mandatory_tags(page):
       inferred = infer_tags_from_content(page)
       page.tags.extend(inferred)
   ```

3. **降级策略**
   ```python
   # 标签验证失败时继续摄取，只记录警告
   except TagValidationError as e:
       logger.warning(f"Tag validation failed: {e}")
       # 继续处理，不阻塞
   ```

---

### 方案 C: 摄取流程并行化

**目标**: 减少端到端延迟

**实施步骤**:

1. **批量入队时并行调度**
   ```python
   # 当前：串行调度6个advance
   for _ in range(6):
       svc.advance()  # 每个等待完成

   # 改进：并行调度
   tasks = [asyncio.create_task(run_pipeline(t)) for t in batch[:6]]
   await asyncio.gather(*tasks)
   ```

2. **Analyzer阶段流式处理**
   ```python
   # 边分析边生成，而不是先完全分析再生成
   async for claim in analyze_stream(content):
       await generate_page_section(claim)
   ```

---

## 质量维度评估

### 摄取质量

| 指标 | 结果 | 评价 |
|------|------|------|
| 页面生成 | 4/5成功 | 良好 |
| Frontmatter完整性 | 100% | 优秀 |
| Body内容 | 0%填充 | 差 |
| 标签准确性 | 有验证警告 | 需改进 |

### 摄取速度

| 阶段 | 估计耗时 | 占比 |
|------|----------|------|
| 调度 | ~5s | 8% |
| 读取 | ~5s | 8% |
| 分析(LLM) | ~30s | 50% |
| 生成(LLM) | ~15s | 25% |
| 写入 | ~5s | 8% |
| **总计** | **~60s** | - |

---

## 本轮测试总结

**成功点**:
- 通过 `/queue/resume` API成功触发了队列消费
- 4/5任务成功完成摄取
- Frontmatter生成质量良好

**待改进**:
- Body内容未填充（P1）
- 标签验证过严（P2）
- 延迟较高（P3）

**修正前几轮结论**:
- 第一轮发现的"队列不消费"问题，实际需要手动调用 `/queue/resume`
- 第三轮发现的"单文件入队缺少advance"问题，实际在resume时被调用
- LLM提供商可达性问题不存在——摄取正常完成