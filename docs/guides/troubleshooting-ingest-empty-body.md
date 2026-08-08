# 摄取故障排查：页面正文全是"（待补充）"

## 症状

WebUI 摄取完成后，生成的 wiki 页面（concept 类型）正文各 slot 全是
"（待补充）"或"（系统占位）"，只有 source 页面正常。

## 根因

pipeline 调用 LLM 时发送了不被接受的 `response_format`，导致 HTTP 400
→ `retry.py` 判定为 permanent 错误（不重试）→ 摄取失败 →
`run_ingest` 创建 source-only stub 页面，正文为空。

### 调用链

```
pipeline (analyzer / generator)
  → 构造非标准 response_format: {"type": "object", "properties": {...}}
  → src/llm/openai_provider.py::complete()
  → 发送给 OpenAI-compatible provider (GLM / DeepSeek / Kimi / MiniMax)
  → 对方返回 HTTP 400 "invalid response_format, should be json_object/json_schema/text/url/b64_json"
  → src/pipeline/retry.py::classify_error → "permanent" (HTTP 400)
  → 不重试 → src/pipeline/ingest.py 创建 source-only stub
```

## 修复

修改 `src/llm/openai_provider.py` 的 `complete()` 方法，在发送前对
`response_format` 做归一化：

```python
if response_format:
    rtype = response_format.get("type")
    # 非标准 schema 降级为 json_object（JSON schema 已内嵌在 prompt 中）
    if rtype not in ("json_object", "json_schema", "text", "url", "b64_json"):
        body["response_format"] = {"type": "json_object"}
    else:
        body["response_format"] = response_format
```

## 验证

使用 `test_reingest.py` 脚本（位于项目根目录）：

```bash
cd <repo_root>
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy ^
  PYTHONIOENCODING=utf-8 PYTHONPATH=. python test_reingest.py
```

**注意脚本的两个坑：**

1. **`PYTHONIOENCODING=utf-8`** — Windows 控制台默认 GBK，print 非 GBK 字符
   会抛 `UnicodeEncodeError`。
2. **`source_path` 必须是项目相对路径** — 传给 `run_ingest()` 的
   `source_path` 要用 `test_file.relative_to(paths.root)`，否则 Reviewer 的
   `reference_consistency` 检查会因 `project_path / source_path` 解析不到
   文件而 REJECTED。

## 变通：换 provider 或 api-key 后怎么办

如果换了 api-key 或切换了 LLM provider（例如从 GLM 换到 DeepSeek），
同样的 `response_format` 问题可能再次出现：

1. 查看服务器日志中是否有 `HTTP 400` 或 `invalid response_format` 关键字
2. 如果确认是 `response_format` 问题，`openai_provider.py` 的归一化逻辑
   已经能处理（只要对方是 OpenAI-compatible 接口）
3. 如果对方完全不接受 `response_format` 参数（如某些旧版 Ollama），
   需要把 `response_format` 整个移除（当前代码不会走到这个分支）

## 相关文件

- [src/llm/openai_provider.py](../../src/llm/openai_provider.py) — 修复位置
- [src/pipeline/retry.py](../../src/pipeline/retry.py) — HTTP 400 → permanent 分类
- [src/pipeline/analyzer.py](../../src/pipeline/analyzer.py) — 非标准 schema 构造
- [src/pipeline/generator.py](../../src/pipeline/generator.py) — 同上
- [test_reingest.py](../../test_reingest.py) — 验证脚本