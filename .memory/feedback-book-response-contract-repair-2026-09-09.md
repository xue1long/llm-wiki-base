# Book 章节响应契约修复（2026-09-09）

## 根因

MiniMax 在章节正文调用中返回了顶层 `list[str]`，而不是编译器要求的
JSON object。原有重试只发送泛化的“不要返回数组”反馈，第二次请求仍可能
重复相同形状，最终生成 `llm_partial`，自动验收失败。

## 修复

在 `src/kc/views/book/wiki/polish_llm.py` 的解析重试边界增加形状感知反馈：
检测到 `list[str]` 时，明确指出实际错误、要求顶层 object，并重新列出编译器
拥有的 section IDs 和必需字段。无法安全归一化的字符串数组仍然 fail-closed，
不会伪造标题、section 或 source provenance。

## 验证

- 新增回归测试：首轮 `list[str]`，定向重试后返回合法 object。
- 章节正文、提示词边界、编译器测试：41 passed。
- 尚未重新调用 MiniMax；失败 preview `d056c1c16cca4272ba718691e003e229`
  仍为 partial，不可直接 promote。
