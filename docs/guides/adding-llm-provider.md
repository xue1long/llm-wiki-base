# 接入新的 LLM / Embedding Provider 指南

> 适用场景：需要为 ruflo-kb 增加新的聊天 / 嵌入模型后端（如 Kimi、DeepSeek、GLM），或切换为本地模型（Ollama 等）时，阅读本文档按步骤配置即可。
>
> 本文档由 2026-07-24 配置 MiniMax（聊天 `MiniMax-Text-01` + 嵌入 `embo-01`@1536）全链路后沉淀，覆盖了当时踩过的真实坑。

---

## 0. 关键约束（先读）

- **向量库维度硬约束**：LanceDB 当前硬编码 **1536 维**（`pa.list_(pa.float32(), 1536)`）。任何 embedding 后端必须输出 1536 维向量，否则需要改 schema 并重建索引。
  - 本地模型（如 `bge-m3` 默认输出 1024）默认不兼容，需额外改造或选择输出 1536 维的模型。
  - Anthropic **没有** embeddings API，不能单独作为向量库后端。
- **真实密钥放 `.env`**（已在 `.gitignore`），不要写进 `env.example` 或提交到仓库。
- 配置加载顺序见第 2 步；若 `set-default` 后不生效，多半是加载环节缺失。

---

## 1. 判断兼容性

| 类型 | 处理方式 |
|---|---|
| **OpenAI 兼容**（Kimi / DeepSeek / GLM / MiniMax 聊天 / Ollama / OpenAI） | 直接用现有 `OpenAIProvider` / `OpenAIEmbeddingProvider`，只需注册 + 映射 key（步骤 2~4） |
| **非 OpenAI 兼容**（如 MiniMax `embo-01` embedding） | 额外写专用适配器（步骤 5） |

---

## 2. 步骤

### 步骤 1：扩展 provider → 环境变量映射

文件：`src/llm/provider_factory.py`

在 `_env_var_for_provider` 字典中增加一项（键是 `llm-providers add` 时用的 provider 名）：

```python
"kimi": "KIMI_API_KEY",
"deepseek": "DEEPSEEK_API_KEY",
"glm": "GLM_API_KEY",
"minimax": "MINIMAX_API_KEY",
```

### 步骤 2：确认配置加载（否则 set-default 不生效）

文件：`src/__init__.py` 顶部，必须尽早执行：

```python
from dotenv import load_dotenv
load_dotenv()
import os
_cfg = os.path.expanduser("~/.config/ruflo-kb/env")
if os.path.exists(_cfg):
    with open(_cfg) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
```

> 这段解决了「`set-default` 只写不读」的历史坑：默认值写在 `~/.config/ruflo-kb/env`，但 `get_default()` 只读 `os.environ`，不 source 就会丢失。

### 步骤 3：注册 provider（CLI）

```bash
# Kimi (Moonshot)
python -m src.cli llm-providers add kimi openai \
  --base-url https://api.moonshot.cn/v1 \
  --model moonshot-v1-8k

# DeepSeek
python -m src.cli llm-providers add deepseek openai \
  --base-url https://api.deepseek.com/v1 \
  --model deepseek-chat

# GLM (智谱)
python -m src.cli llm-providers add glm openai \
  --base-url https://open.bigmodel.cn/api/ai/v1 \
  --model glm-4
```

- 省略 `--api-key`：运行时从 `KIMI_API_KEY` 等环境变量读取（靠步骤 1 的映射）。
- ⚠️ 注意：`add` 命令曾对**非 ollama 类型丢弃 `--base-url`**（误打到 `api.openai.com`），现已修复；若遇到 endpoint 错误，检查此处是否保留 base-url。
- base_url / 模型名以各厂商最新文档为准。

### 步骤 4：设为默认（可选）

```bash
python -m src.cli llm-providers set-default kimi
```

写入 `~/.config/ruflo-kb/env` 的 `RUFLO_LLM_PROVIDER`。

### 步骤 5（仅非 OpenAI 兼容 embedding）：写专用适配器

以 MiniMax `embo-01` 为例，文件：`src/llm/minimax_embed.py`

- 请求体用 `{"model":"embo-01","texts":[...],"type":"db"}`（**不是** OpenAI 的 `input`）
- 响应解析 `vectors`（**不是** `data`）
- 实现 `embed()` 返回 `EmbeddingResponse`（1536 维）

并在 `src/llm/provider_factory.py` 的 `create_embedding_provider` 加路由（放在 `provider=="openai"` 分支**之前**）：

```python
if provider and "minimax" in str(provider).lower() or (endpoint and "minimax" in endpoint):
    return MiniMaxEmbeddingProvider(...)
```

### 步骤 6：确认 embedding 接线（server）

文件：`src/server/app.py`，启动期创建 embedding provider 时：

- `api_key` 必须经 `_env_var_for_provider(default.name)` 从 env 取，**不要**直接用 `default.api_key`（常为空 → 错误回落 `OPENAI_API_KEY`）
- `model`：minimax 回落 `embo-01`，其它回落 `text-embedding-3-small`
- `dimension=None`（让模型返回原生维，embo-01=1536 自动匹配 schema，无需改维度 / 重建索引）

---

## 3. 厂商速查表

| 厂商 | base_url | 聊天模型 | embedding | 兼容 |
|---|---|---|---|---|
| Kimi | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` | OpenAI 兼容（维数需确认） | OpenAI |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | OpenAI 兼容（维数需确认） | OpenAI |
| GLM | `https://open.bigmodel.cn/api/ai/v1` | `glm-4` | OpenAI 兼容（维数需确认） | OpenAI |
| MiniMax | `https://api.minimax.chat/v1` | `MiniMax-Text-01` | `embo-01`（非兼容，1536） | 聊天兼容 / 嵌入非兼容 |
| Ollama | `http://localhost:11434/v1` | 本地模型 | 本地模型 | OpenAI |

> 注：Kimi / DeepSeek / GLM 的 embedding 端点与维数需自行确认是否为 **1536**；非 1536 需改 schema。

---

## 4. 验证清单

1. **聊天**：`create_llm_provider("kimi")` → 正常回复
   - 必须传 `messages=[{"role":"user","content":"..."}]` 列表，传字符串会被拒 400
2. **Embedding**：`create_embedding_provider(...)` → 返回向量，检查 `len(vec) == 1536`
3. **起服务**：`python -m src.cli serve`，走 `POST /api/v1/projects/ruflo-kb/ingest` 实测一次小文档

---

## 5. 常见坑（历史修复记录）

- key 填进 `env.example` 而非 `.env` → 代码只 `load_dotenv()` 读 `.env`，key 接不上
- `set-default` 后不生效 → 检查 `src/__init__.py` 是否加载了 `~/.config/ruflo-kb/env`
- embedding 维数不匹配 → 落在 1536 硬约束上，检查 provider 输出维数
- 非兼容 embedding 直接套 `OpenAIEmbeddingProvider` → 返回空 `data`，需专用适配器（见步骤 5）
- `add` 命令非 ollama 类型丢 `--base-url` → endpoint 错误，现已修复
