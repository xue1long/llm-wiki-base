# Stage 6 调研记录(H6 加固)

## 命令输出

```
$ git grep -n "extract_relations\|relation_extractor" src/ scripts/
src/pipeline/v7_extract/__init__.py:22:  6. relation_extractor      → extract_relations(pages) -> Relations
src/pipeline/v7_extract/relation_extractor.py:37:def extract_relations(pages: list[Any], *, llm: Any = None) -> list[PageRelation]:
src/pipeline/v7_extract/relation_extractor.py:69:            prompt_kind="extract_relations",
src/pipeline/v7_extract/wiki_writer.py:29:from .relation_extractor import PageRelation
src/wiki/migrate/v2_wikilinks.py:39:def extract_relations(body: str, *, current_page_id: str) -> list[dict[str, str]]:
```

## 结论

- `src/pipeline/v7_extract/relation_extractor.py` **已实现** LLM + heuristic 双模式(行 37、69)
- `wiki_writer.py` 引用 `PageRelation`(行 29),但只用作类型注解,**不在主链路调用 `extract_relations`**
- `__init__.py:22` 文档描述"6. relation_extractor → extract_relations(pages) -> Relations"
- v3 架构第 5 节流程图把 Stage 6 画在 Stage 5 与 Stage 7 之间
- **scripts/ 无任何 `extract_relations` 或 `relation_extractor` 调用方**

## 决策

- **现状:** Stage 6 实现完整,**但默认不调用**
- **plan Task 6 整改合理:** 把 Stage 6 文档改为"可选 best-effort 后处理,默认不接入首轮 apply"
- **代码侧不必改:** `relation_extractor.py` 保留,供后续需要时手动调用(例如 `python -c "from src.pipeline.v7_extract.relation_extractor import extract_relations; ..."`)
- **不需要新增"Stage 6 默认 disable"配置项**(plan-audit 第 9 节 9.6 待补中提到的代码改动可以省)
