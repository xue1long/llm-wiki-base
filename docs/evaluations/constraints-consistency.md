# CONSTRAINTS.md 一致性校验报告

> 校验对象：`docs/CONSTRAINTS.md` (v1.0)
> 校验日期：2026-08-03
> 方法：实际阅读被校验文档 + 逐条读它的上游源文件（`CLAUDE.md` / `pyproject.toml` / `src/wiki/core/types.py` / `src/wiki/features/tag_namespace.py` / `src/pipeline/analyzer.py` / `src/pipeline/generator.py`）。**未修改任何文件。**

---

## 总评

文档**框架可用、大部分声明准确**，但 §3.4（受控标签命名空间）存在 **3 处严重错误**——其中 2 处会让照文档调用 API 的开发者直接报错，1 处是事实性倒错（把已配置好的东西说成"未配置"）。另有 4 处轻微行号偏差。

---

## ✅ 已验证准确的部分

| 章节 | 声明 | 实测结论 |
|------|------|---------|
| §1.1 | 四大行为准则（想清楚/极简/外科手术/目标驱动） | `CLAUDE.md:356/366/378/394` 四章标题完全吻合 ✅ |
| §1.2 | WikiPage 加字段须双改 `to_frontmatter_dict`+`from_dict` | `CLAUDE.md:307` 原文吻合 ✅ |
| §1.2 | 原子写走 `safe_write`+`DELETE_SENTINEL` | `CLAUDE.md:308` 吻合 ✅ |
| §1.2 | 旧模块路径不再别名 | `CLAUDE.md:346` 吻合 ✅ |
| §1.2 | 事件处理器 `event_bus.on` 注册 / AtomicContext | `CLAUDE.md:205` 吻合 ✅ |
| §1.2 | Test 目录镜像 / conftest 复制 | `CLAUDE.md:227` 吻合 ✅ |
| §1.2 | TDD per task | `CLAUDE.md:258` 吻合 ✅ |
| §2.2 | 运行时依赖 10 个 + dev 4 个 | `pyproject.toml:5-16` 逐字吻合 ✅ |
| §2.1 | 禁用重型框架 / 零 DB / 静态 web | 与代码实际（`routes` thin adapter、`web/` 纯静态、Markdown 真相源）一致 ✅ |
| §3.1 | 页面 ID 正则 / 64 上限 / 保留字 index·log | 与 `wiki-spec.md` 一致（此前已核对）✅ |
| §3.2 | Frontmatter required `id/title/type` | `types.py:55-57` 必填字段吻合 ✅ |
| §3.3 | Body `min1/max50000` + 允许子集 | 与 `wiki-spec.md` 一致 ✅ |
| §3.4 | 10 个中文前缀 + `TAG_VALUES` 值域 | `tag_namespace.py:15-43` 逐字吻合 ✅ |
| §5.1/5.2/5.3 | 标签前缀数、Web UI、lint 配置偏差记录 | 基本准确 ✅ |

---

## 🔴 严重错误（必须修正）

### E1 — `MANDATORY_PAIRS` 声称"为空"是错的

- **文档声称**（§3.4 第 164 行 + §5.4）：
  > "当前 `MANDATORY_PAIRS = []` 为空——UGC 强制配对（素材/ugc + 可信度/ugc）目前**硬编码在 analyzer / generator 提示词**里，非配置驱动"
- **实际代码**（`tag_namespace.py:49-52`）：
  ```python
  MANDATORY_PAIRS: list[tuple[str, str]] = [
      ("素材", "ugc"),
      ("可信度", "ugc"),
  ]
  ```
  **非空**，且 `build_tag_prompt_section()`（line 180-182）会读取它动态注入提示词。
- **后果**：开发者误以为配对未配置，可能重复硬编码或在治理层误判状态。连带使 §5.4 的偏差记录也成立错误结论。
- **整改**：改为"已配置 2 个配对（素材/ugc、可信度/ugc），通过 `build_tag_prompt_section()` 配置驱动注入提示词"。

### E2 — 标签校验函数名/签名全部写错（照文档调用会报错）

| 文档写的函数 | 实际代码 | 影响 |
|-------------|---------|------|
| `is_valid_prefix(tag)` `@:61` | 函数名是 **`is_valid(tag)`** `@:59` | `AttributeError` |
| `is_valid_value(prefix, value)` `@:80` | 实际是 **`is_valid_value(tag)`** `@:74`（单参数） | 多传参 → `TypeError` |
| `get_mandatory_pairs()` `@:88` | **该函数不存在**；实际是模块级变量 `MANDATORY_PAIRS` + `missing_mandatory_tags(tags)` `@:114` / `validate_tag_compliance(tags)` `@:140` | `AttributeError` |

- **后果**：这是文档给开发者的"API 速查"，三处里两处函数名错、一处函数根本不存在——开发者照抄必崩。
- **整改**：替换为正确 API 清单（见 §末附正确签名）。

### E3 — "配对硬编码在提示词、非配置驱动"与事实相反

- **文档声称**（§3.4）：配对"硬编码在 analyzer / generator 提示词里，非配置驱动"。
- **实际**（`generator.py:28,42-44`）：
  ```python
  from ..wiki.features.tag_namespace import ... build_tag_prompt_section
  # Dynamic tag namespace rules — built from TAG_VALUES and MANDATORY_PAIRS.
  TAG_NAMESPACE_RULES = build_tag_prompt_section()
  ```
  配对是**配置驱动**读取 `MANDATORY_PAIRS` 注入的。提示词里确有硬编码的**前缀说明列表**（analyzer.py:70、generator.py:735/1293），但其值与 `TAG_PREFIXES` 一致，且配对逻辑本身不在其中。
- **后果**：把"已配置化"误判为"硬编码"，会误导技术债务 #11 的归因（#11 应只指"前缀说明文案的重复"，而非配对规则）。
- **整改**：改为"配对经 `build_tag_prompt_section()` 配置驱动；仅前缀说明文案在提示词中重复出现（技术债务 #11 范畴）"。

---

## 🟡 轻微偏差（行号/列举不完整）

| 位置 | 文档写 | 实际 | 影响 |
|------|--------|------|------|
| §1.1 | 行为准则章 `376 / 392` | `378 / 394`（§3/§4 章）| 内容对，行号偏移 2 |
| §1.2 | "提交粒度 `CLAUDE.md:258`" | commit 前缀在 `263`，`258` 是 TDD | 行号错指 |
| §1.3 | ruff 在 `pyproject.toml:36` | `[tool.ruff]` 在 `:32` | 行号偏下 |
| §1.3 | ruff ignore 列举 `E501,B904,B905,B028,E402,B007,E741` | 实际还有 `E702/F841/C408/E701/C416/B017` 等 | 标注"多数"可接受，但易让人以为就这些 |

---

## 附：正确的标签命名空间 API（供修订 §3.4 使用）

```python
# src/wiki/features/tag_namespace.py
TAG_PREFIXES: dict[str, str]                       # :15  — 10 个中文前缀
TAG_VALUES: dict[str, set[str] | None]            # :32  — 值域；None=自由
MANDATORY_PAIRS: list[tuple[str, str]]            # :49  — [("素材","ugc"),("可信度","ugc")]

is_valid(tag: str) -> bool                        # :59  — 前缀受控校验
parse(tag: str) -> tuple[str, str] | None         # :64
is_valid_value(tag: str) -> bool                  # :74  — 值在值域内
allowed_values_for(prefix: str) -> set | None    # :86
validate_tags(tags) -> list[str]                  # :91  — 非法前缀
validate_tag_values(tags) -> list[str]            # :96  — 值越界
missing_mandatory_tags(tags) -> list[str]         # :114 — 缺配对
validate_tag_compliance(tags) -> None             # :140 — 抛 TagValidationError
build_tag_prompt_section() -> str                 # :163 — 动态生成提示词片段
```

---

## 整改建议汇总

| 编号 | 动作 | 紧急度 |
|------|------|--------|
| E1 | §3.4 与 §5.4 的 `MANDATORY_PAIRS=[]` 改为"已配置 2 个配对" | 🔴 高 |
| E2 | §3.4 校验函数段替换为上表正确 API（函数名/签名/行号） | 🔴 高 |
| E3 | §3.4 "配对硬编码"改为"配置驱动（build_tag_prompt_section）" | 🔴 高 |
| 行号 | §1.1 改 378/394；§1.2 提交粒度改 263；§1.3 ruff 改 32 | 🟡 低 |
| ignore | §1.3 补全 ignore 列表或注明"仅示例" | 🟡 低 |

> 注：本错误（尤其 E1/E3）牵连了此前多份文档中的同一误判——`tag-namespace-evaluation.md`、`semantic-taxonomy-feasibility.md`、摄取方案、以及项目记忆里"MANDATORY_PAIRS 为空、配对硬编码在提示词"的描述均需同步纠正。
