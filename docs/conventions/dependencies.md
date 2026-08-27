# 依赖规范（Dependency Conventions）

> 适用范围：`pyproject.toml [project.dependencies]` 与
> `[project.optional-dependencies]` 中的所有第三方 Python 包。
>
> 本规范定稿的目的是**控制依赖膨胀**、**保证许可证合规**、
> **避免代理环境装包失败**——这是 ruflo-kb 项目在 cp314 + 代理环境下
> 的核心痛点之一（详见 `docs/environment/SETUP.md` §2）。

## 1. 决策树（强制）

新功能需要引入第三方包时，按以下顺序判断：

```text
1. 能不能用 stdlib？→ 是 → 用 stdlib（决策终止）
2. 项目已装（pyproject.toml 已有）？→ 是 → 直接 import（决策终止）
4. 装新依赖前 → 先写 ADR：docs/adr/YYYY-MM-DD-<dep-name>.md
   - ADR 必填：许可证 / 尺寸预算 / 离线 wheel / 替代方案评估
5. ADR 通过 → pip install → 提交 pyproject.toml
```

- **禁止顺序**：跳过 stdlib 直接装第三方 → 跳过 ADR 直接装第三方 → 都被拒绝。

```python
# ✅ Good（决策树示例）
import json                              # 1. stdlib 优先
import asyncio                           # 1. stdlib 优先
from pathlib import Path                 # 1. stdlib 优先

import httpx                             # 2. 已装（pyproject.toml dependencies）
import yaml                              # 2. 已装（pyyaml>=6.0）
import pypdf                             # 2. 已装（pypdf>=4.0.0）

# ❌ Bad
import requests                          # httpx 已装 → 重复
import simplejson                        # json 已够用 → 跳过 stdlib
import magic                            # 没 ADR 直接装
```

## 2. stdlib 优先

- **任何"看起来像 stdlib"的场景**，先查 [Python 3.11+ stdlib 索引](https://docs.python.org/3/library/)：
  - HTTP：`urllib.request` / `http.client` / `httpx`（已装）。
  - JSON：`json` / `dataclasses.asdict`。
  - 并发：`asyncio` / `concurrent.futures` / `multiprocessing`。
  - 文件 IO：`pathlib` / `shutil` / `tempfile`。
  - 压缩：`gzip` / `zipfile` / `tarfile`。
  - 哈希：`hashlib`（替代第三方 `xxhash` / `blake3`，除非性能瓶颈已量化）。
- **优先 stdlib 不是教条**：当性能 / API 友好度明显占优且有 ADR 时，仍可引入
  第三方；但 ADR 必须量化收益（如"json 解析耗时 200ms，orjson 12ms"）。

## 3. 已有依赖优先

引入新依赖前**必须 grep `pyproject.toml`**（项目当前依赖列表见下表）：

| 类别 | 包 | 已装版本下限 | 用途 |
|---|---|---|---|
| 向量库 | `lancedb` | `>=0.4.0` | 1536-dim 向量存储 |
| 向量依赖 | `pyarrow` | （离线 wheel） | LanceDB 列存依赖 |
| PDF | `pypdf` | `>=4.0.0` | PDF 文本提取 |
| DOCX | `python-docx` | `>=1.0.0` | DOCX 文本提取 |
| XLSX | `openpyxl` | `>=3.1.0` | XLSX 表格提取 |
| YAML | `pyyaml` | `>=6.0` | 配置 / frontmatter |
| HTTP 客户端 | `httpx` | `>=0.25.0` | 异步 HTTP |
| 系统路径 | `platformdirs` | `>=4.0` | `~/.config` 解析 |
| MCP | `mcp` | `>=0.1.0` | stdio MCP 服务 |
| Web 框架 | `fastapi` | `>=0.100.0` | HTTP API |
| ASGI | `uvicorn` | `>=0.31.0` | ASGI server |
| 配置 | `pydantic-settings` | `>=2.0.0` | 配置加载 |
| Web 检索 | `tavily-python` | （在线） | Tavily 搜索 |
| Dev | `pytest` / `pytest-asyncio` / `ruff` / `mypy` | （dev extra） | 测试 / lint / 类型 |
| Embedding（可选） | `sentence-transformers` | `>=2.2.0` | 本地 embedding fallback |

```text
✅ 想用 orjson 替代 json → 先查"pyyaml/httpx 已装"看是否有同类 → 没有 → 评估 ADR
❌ 直接 pip install magic → 跳步
```

## 4. 许可证白名单（与 ruflo-kb 一致）

- **允许**：
  - **MIT**（最宽松，默认可接受）。
  - **BSD-2-Clause / BSD-3-Clause**（含 `Apache-2.0 WITH LLVM-exception` 子类）。
  - **Apache-2.0**（带显式 NOTICE 文件）。
  - **PSF**（Python Software Foundation License，stdlib 同类）。
  - **MPL-2.0**（弱传染，可用于文件级 copyleft）。
  - **ISC**（与 BSD 等价）。
- **不允许**（除非有显式 ADR + 法务复核）：
  - **GPL / LGPL / AGPL**（强传染；可能影响商业分发）。
  - **SSPL / BUSL / Elastic License**（源代码可用但商业受限）。
  - **自定义 / "Source-Available"**（无 OSI 认证）。
- **未知 / 未声明** → 拒绝（即使 ADR 也不接受）。

```bash
# 校验依赖许可证（计划 L-2 阶段补自动化）
pip show <pkg> | grep License
# 或 pip-licenses：
pip install pip-licenses && pip-licenses --format=markdown
```

## 5. 依赖尺寸预算

- **单依赖 wheel 安装体积 < 5 MB**（解压后 `< 15 MB`）。
- **超出 5 MB 的依赖**必须在 ADR 中量化收益（性能 / API 友好度），且必须提供
  **离线 wheel** 路径（见 §6）。
- **典型重依赖**（项目已 ADR）：
  - `pyarrow`（~30 MB）：LanceDB 列存依赖——离线 wheel 已落地。
  - `lancedb`（~12 MB）：核心向量库——离线 wheel 已落地。
  - `sentence-transformers`（`embedding` extra，~150 MB）：仅在用户显式启用
    embedding profile 时安装；CI 默认**不装**。

```text
✅ httpx (~1.5 MB), pypdf (~0.5 MB), pyyaml (~0.2 MB)
✅ markdown-it-py (~1 MB), pydantic-settings (~0.8 MB)
⚠ pyarrow (~30 MB) → 已 ADR + 离线 wheel
❌ 引入 torch (~700 MB) 直接 transitive 依赖 → ADR 必须量化收益
```

## 6. 离线 wheel 路径

- **目标**：在 127.0.0.1:7897 代理环境下，pyarrow / lancedb 等大型 native wheel
  超时（见 `docs/environment/SETUP.md` §2）；项目通过**预下载 + 离线安装**绕过。
- **目录**：`docs/environment/wheels/<pkg>-<version>-<py_version>-<platform>.whl`。
- **安装命令**：
  ```bash
  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy \
    pip install docs/environment/wheels/pyarrow-25.0.0-cp314-cp314-win_amd64.whl \
                  docs/environment/wheels/lancedb-0.27.1-cp39-abi3-win_amd64.whl
  ```
- **新依赖 ADR 通过后**，作者负责：
  1. 把 wheel 上传到 `docs/environment/wheels/`（git LFS 或 release asset）。
  2. 更新 `docs/environment/SETUP.md` 中的安装命令。
  3. 更新 `docs/environment/requirements-cp314.txt`（如有）。

```text
✅ 装 pyarrow / lancedb → 走 docs/environment/wheels/ 离线安装
❌ 直接 pip install（被代理超时拦截）
```

## 7. 反例速查

```text
# ❌ 反例 1：跳过 stdlib 直接装第三方
import requests                    # httpx 已装 + urllib 可用 → 不需要 requests

# ❌ 反例 2：跳过 ADR 直接装
pip install beautifulsoup4         # 应先 ADR（许可证 OK，但需评估 stdlib html.parser）

# ❌ 反例 3：GPL 传染
pip install gpl-licensed-pkg       # 直接拒绝

# ❌ 反例 4：超出尺寸预算无 ADR
pip install torch                  # ~700 MB 必须 ADR 量化收益

# ❌ 反例 5：代理环境下装包超时
pip install pyarrow                # 必须走 docs/environment/wheels/ 离线
```

## 8. ADR 模板（精简版）

新依赖 ADR 必填字段（完整模板见 `docs/adr/_template.md`）：

```yaml
context: |
  为什么需要这个依赖？现有 stdlib / 已装依赖为何不够？
decision: "选择包 <name>@<version-low>"
rationale:
  - 许可证: MIT/BSD-3-Clause/Apache-2.0/PSF（MPL-2.0/ISC 允许）
  - 尺寸: <wheel 体积 MB>（满足 <5MB 阈值 / 已量化超标理由>）
  - 替代方案: <已尝试 stdlib / 已装依赖的具体对比>
consequences:
  - 引入代价: <安装时间 / wheel 落地路径>
  - 维护负担: <更新频率 / 已知 CVE>
  - 触发重审: <什么时候应重新评估>
```

## 9. Lint / 校验

- **路线 v2.2 计划 L-2** 补自动化：
  - `scripts/check_dependencies.py`：扫描 `pyproject.toml` 与已装包，
    输出许可证白名单 / 尺寸阈值违规。
  - `tests/test_dependencies/test_whitelist.py`：断言所有 transitive 依赖符合白名单。
- **当前阶段**：人工 review + ADR 守门。