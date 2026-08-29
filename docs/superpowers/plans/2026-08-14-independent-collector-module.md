# 独立采集模块设计方案

> **日期**: 2026-08-14
> **状态**: Draft
> **目标**: 设计一个独立可解耦的采集模块，支持接收 PDF、文本文档、链接、图片等输入，转换为 Markdown 后写入项目实例的 `raw/sources/`

---

## 0. 现状分析

### 0.1 现有采集链路

```
HTTP API (/api/v1/projects/{id}/ingest)
  → services/ingest.py (enqueue_source)
    → queue (异步队列)
      → pipeline/collector.py (collect) — 格式读取 + 权限检查 + EventBus
        → utils/extract/{pdf,office,html}.py — 纯文本提取
      → pipeline/ingest.py (run_ingest) — LLM 分析 + 生成 + 写盘
```

### 0.2 可复用资产

| 资产 | 路径 | 耦合度 | 复用方式 |
|------|------|--------|----------|
| PDF 提取 | `utils/extract/pdf.py` | 🟢 无耦合 | 直接 import |
| Office 提取 | `utils/extract/office.py` | 🟢 无耦合 | 直接 import |
| HTML 提取 | `utils/extract/html.py` | 🟢 无耦合 | 直接 import |
| 文件上传路由 | `server/routes/files.py` | 🟡 轻度 | 已有 `POST /upload`，可复用 |
| 文件上传服务 | `services/files.py::upload_file` | 🟡 轻度 | 已有，可复用 |
| 路径管理 | `wiki/core/paths.py::WikiPaths` | 🟢 无耦合 | 直接 import |
| LLM Provider | `llm/base.py::LLMProvider` | 🟡 轻度 | 抽象接口，用于图片 OCR |

### 0.3 缺失能力

| 能力 | 说明 |
|------|------|
| **图片处理** | 现有 extract 模块不支持图片（jpg/png/gif/webp） |
| **图片 OCR/描述** | 需要调用 LLM Vision API 或专用 OCR 服务 |
| **链接内容抓取** | `collector.py` 有 URL 抓取逻辑但耦合 EventBus/permissions |
| **"聊天发送文件"接收** | 需要新的接收层 |
| **格式转换 → Markdown** | 现有 extract 输出纯文本，缺少结构化 Markdown 转换 |

---

## 1. 模块设计

### 1.1 架构总览

```
独立采集模块 (src/collector/)
│
├── receiver/           # 输入接收层（可选，按场景实现）
│   ├── file_receiver.py    # 接收文件字节/路径
│   ├── url_receiver.py     # 接收 URL
│   └── chat_receiver.py    # 接收聊天消息中的文件
│
├── converter/          # 格式转换层（核心）
│   ├── base.py             # ConverterBase 抽象接口
│   ├── pdf_converter.py    # PDF → Markdown（复用 extract/pdf.py）
│   ├── office_converter.py # DOCX/XLSX → Markdown（复用 extract/office.py）
│   ├── html_converter.py   # HTML → Markdown（复用 extract/html.py + 新增 md 转换）
│   ├── text_converter.py   # TXT/MD → Markdown（直通）
│   ├── image_converter.py  # 图片 → Markdown（新增，调 LLM Vision）
│   └── url_converter.py    # URL → Markdown（抓取 + 转换）
│
├── writer/             # 输出层
│   └── raw_writer.py       # 写入 <project>/raw/sources/*.md
│
└── collector.py        # 顶层编排：接收 → 转换 → 写入
```

### 1.2 核心接口

```python
# src/collector/converter/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

@dataclass
class ConvertResult:
    """格式转换结果"""
    content: str           # 转换后的 Markdown 文本
    title: str             # 提取的标题
    metadata: dict         # 额外元数据（页数、作者等）
    source_type: str       # 原始类型标识（pdf/docx/image/url/text）
    original_path: str     # 原始文件路径或 URL

class ConverterBase(ABC):
    """格式转换器抽象基类"""

    @abstractmethod
    def can_handle(self, source: str | Path) -> bool:
        """判断是否能处理该源"""
        ...

    @abstractmethod
    async def convert(self, source: str | Path, *, content: bytes | None = None) -> ConvertResult:
        """将源转换为 Markdown

        Args:
            source: 文件路径或 URL
            content: 可选的文件字节内容（避免重复读取）
        """
        ...
```

### 1.3 顶层编排

```python
# src/collector/collector.py
class Collector:
    """独立采集器 — 接收输入，转换为 Markdown，写入 raw/sources/"""

    def __init__(self, project_root: Path, llm_provider=None):
        self.project_root = project_root
        self.paths = WikiPaths(project_root)
        self.llm_provider = llm_provider  # 图片处理需要
        self._converters = self._build_converter_chain()

    def _build_converter_chain(self) -> list[ConverterBase]:
        """构建转换器链（按优先级排列）"""
        return [
            ImageConverter(self.llm_provider),  # 图片 → Markdown
            PdfConverter(),                      # PDF → Markdown
            OfficeConverter(),                   # DOCX/XLSX → Markdown
            HtmlConverter(),                     # HTML → Markdown
            TextConverter(),                     # TXT/MD → 直通
            UrlConverter(),                      # URL → 抓取 + 转换
        ]

    async def collect(
        self,
        source: str | Path,
        *,
        content: bytes | None = None,
        filename: str | None = None,
    ) -> ConvertResult:
        """主入口：接收任意输入，转换为 Markdown"""
        # 1. 选择合适的转换器
        converter = self._find_converter(source)
        if converter is None:
            raise UnsupportedSourceError(f"No converter for: {source}")

        # 2. 执行转换
        result = await converter.convert(source, content=content)

        # 3. 写入 raw/sources/
        raw_path = self.write_to_raw(result, filename=filename)
        result.original_path = raw_path

        return result

    def write_to_raw(self, result: ConvertResult, filename: str | None = None) -> str:
        """将转换结果写入 raw/sources/"""
        raw_dir = self.paths.raw_sources
        raw_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        name = filename or self._derive_filename(result)
        dest = raw_dir / name

        # 如果是纯文本/MD，直接写入
        if result.source_type in ("text", "md"):
            dest.write_text(result.content, encoding="utf-8")
        else:
            # 其他类型：写转换后的 Markdown
            dest.write_text(result.content, encoding="utf-8")

        return f"raw/sources/{name}"
```

---

## 2. 各转换器设计

### 2.1 PDF 转换器

```python
# src/collector/converter/pdf_converter.py
class PdfConverter(ConverterBase):
    """PDF → Markdown，复用 utils/extract/pdf.py"""

    def can_handle(self, source):
        return str(source).endswith(".pdf")

    async def convert(self, source, *, content=None):
        from ...utils.extract.pdf import extract_pdf_text
        # 写入临时文件（如果是 bytes）
        if content:
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.write(content)
            tmp.close()
            source = tmp.name

        text = extract_pdf_text(str(source))
        title = Path(source).stem

        return ConvertResult(
            content=self._to_markdown(text),
            title=title,
            metadata={"pages": text.count("<!-- page:") + 1},
            source_type="pdf",
            original_path=str(source),
        )

    def _to_markdown(self, text: str) -> str:
        """将提取的纯文本转换为结构化 Markdown"""
        # 保留 page 标注，清理多余空行
        lines = text.split("\n")
        result = []
        for line in lines:
            if line.startswith("<!-- page:"):
                result.append(f"\n---\n{line}\n")
            else:
                result.append(line)
        return "\n".join(result)
```

### 2.2 图片转换器（新增能力）

```python
# src/collector/converter/image_converter.py
class ImageConverter(ConverterBase):
    """图片 → Markdown，调用 LLM Vision API"""

    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

    def can_handle(self, source):
        return Path(str(source)).suffix.lower() in self.IMAGE_EXTS

    async def convert(self, source, *, content=None):
        import base64

        # 读取图片
        if content:
            img_b64 = base64.b64encode(content).decode()
            ext = Path(str(source)).suffix.lower()
        else:
            img_bytes = Path(str(source)).read_bytes()
            img_b64 = base64.b64encode(img_bytes).decode()
            ext = Path(str(source)).suffix.lower()

        # 调用 LLM Vision API
        mime = {
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".gif": "image/gif",
            ".webp": "image/webp", ".bmp": "image/bmp",
        }.get(ext, "image/png")

        prompt = (
            "请仔细阅读这张图片，提取其中的所有文字内容，并描述图片的主要内容。\n"
            "如果图片包含表格，请用 Markdown 表格格式输出。\n"
            "如果图片是图表/示意图，请描述其结构和关键信息。\n"
            "输出格式：\n"
            "## 图片内容\n\n[提取的文字]\n\n## 图片描述\n\n[描述]"
        )

        response = await self.llm_provider.complete(
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:{mime};base64,{img_b64}"
                    }}
                ]
            }]
        )

        title = Path(str(source)).stem
        return ConvertResult(
            content=f"# {title}\n\n{response.content}",
            title=title,
            metadata={"format": ext, "ocr_method": "llm_vision"},
            source_type="image",
            original_path=str(source),
        )
```

### 2.3 URL 转换器

```python
# src/collector/converter/url_converter.py
class UrlConverter(ConverterBase):
    """URL → Markdown，抓取网页内容并转换"""

    def can_handle(self, source):
        s = str(source)
        return s.startswith("http://") or s.startswith("https://")

    async def convert(self, source, *, content=None):
        import httpx
        from ...utils.text import html_to_text

        # 抓取
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(str(source), follow_redirects=True)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")

        # PDF 链接
        if "pdf" in content_type:
            return await PdfConverter().convert(source, content=resp.content)

        # 图片链接
        if any(t in content_type for t in ("image/png", "image/jpeg", "image/webp")):
            return await ImageConverter(self.llm_provider).convert(source, content=resp.content)

        # HTML → 文本 → Markdown
        text = html_to_text(resp.text)
        title = self._extract_title(resp.text) or str(source)

        return ConvertResult(
            content=f"# {title}\n\n{text}",
            title=title,
            metadata={"url": str(source), "content_type": content_type},
            source_type="url",
            original_path=str(source),
        )
```

### 2.4 Office / Text / HTML 转换器

Office、Text、HTML 转换器结构类似，核心差异在底层提取：

| 转换器 | 底层提取 | 新增逻辑 |
|--------|----------|----------|
| `OfficeConverter` | `extract_office_text()` / `extract_xlsx_text()` | 加 Markdown 表格格式化 |
| `TextConverter` | 直接读取 | 仅加标题 |
| `HtmlConverter` | `html_to_text()` + `convert_html_tables_to_markdown()` | 加标题提取 |

---

## 3. 集成方案

### 3.1 方案 A：独立模块 + 新增 HTTP 路由（推荐）

在现有 HTTP API 上新增一个「智能采集」端点，复用现有上传机制：

```
POST /api/v1/projects/{id}/collect
  - Content-Type: multipart/form-data
  - file: 上传的文件（PDF/DOCX/图片等）
  - url: 要抓取的 URL（与 file 二选一）

响应:
  {
    "status": "ok",
    "raw_path": "raw/sources/xxx.md",
    "title": "提取的标题",
    "source_type": "pdf",
    "metadata": {...}
  }
```

**优势**：
- 复用现有 `files.py` 的上传基础设施
- 独立模块可被 CLI、MCP、脚本等多入口调用
- 不侵入现有 pipeline/collector 链路

### 3.2 方案 B：扩展现有 Collector

在 `pipeline/collector.py` 的 `collect()` 函数中增加图片/URL 处理分支。

**劣势**：耦合 EventBus/permissions，不可独立使用。**不推荐。**

### 3.3 方案 C：Capture 路由扩展

扩展现有 `POST /capture` 端点，增加文件上传能力。

**劣势**：Capture 是"跳过 LLM 的快速录入"，采集模块需要 LLM（图片 OCR），语义不符。**不推荐。**

---

## 4. 实现任务拆分

### Task 1: 模块骨架 + 转换器接口

**文件**: `src/collector/__init__.py`, `src/collector/converter/base.py`
**测试**: `tests/test_collector/test_base.py`

- 定义 `ConvertResult` 数据类
- 定义 `ConverterBase` 抽象接口
- 定义 `UnsupportedSourceError` 异常

### Task 2: PDF 转换器

**文件**: `src/collector/converter/pdf_converter.py`
**测试**: `tests/test_collector/test_pdf_converter.py`

- 复用 `utils/extract/pdf.py`
- 纯文本 → 结构化 Markdown（保留 page 标注）
- 支持 bytes 输入（避免重复写临时文件）

### Task 3: Office 转换器

**文件**: `src/collector/converter/office_converter.py`
**测试**: `tests/test_collector/test_office_converter.py`

- 复用 `utils/extract/office.py`
- DOCX 段落 → Markdown
- XLSX 行 → Markdown 表格

### Task 4: Text / HTML 转换器

**文件**: `src/collector/converter/text_converter.py`, `src/collector/converter/html_converter.py`
**测试**: `tests/test_collector/test_text_converter.py`, `tests/test_collector/test_html_converter.py`

- TXT/MD 直通 + 标题提取
- HTML → 文本 + 表格 Markdown 化

### Task 5: 图片转换器（新增能力）

**文件**: `src/collector/converter/image_converter.py`
**测试**: `tests/test_collector/test_image_converter.py`

- 支持 jpg/png/gif/webp/bmp
- 调用 LLMProvider.complete() 的 Vision 模式
- 提取文字 + 描述图片内容
- 输出结构化 Markdown

### Task 6: URL 转换器

**文件**: `src/collector/converter/url_converter.py`
**测试**: `tests/test_collector/test_url_converter.py`

- httpx 抓取网页
- 根据 Content-Type 分派（HTML/PDF/图片）
- 标题提取
- 链接内图片 → Markdown

### Task 7: 顶层编排器

**文件**: `src/collector/collector.py`
**测试**: `tests/test_collector/test_collector.py`

- `Collector` 类：转换器链 + 写入 raw/sources/
- `collect()` 主入口
- `write_to_raw()` 输出方法

### Task 8: HTTP 路由集成

**文件**: `src/server/routes/collect.py`
**测试**: `tests/test_server/test_collect.py`

- `POST /api/v1/projects/{id}/collect` 端点
- 支持 multipart/form-data（文件上传）和 JSON（URL）
- 复用 `services/files.py` 的项目解析

### Task 9: CLI 集成（可选）

**文件**: `src/cli.py` 扩展
**测试**: 手动测试

- `python -m src.cli collect <project_id> <source>` 命令
- 支持文件路径和 URL

---

## 5. 依赖关系

```
Task 1 (骨架)
  ├── Task 2 (PDF)
  ├── Task 3 (Office)
  ├── Task 4 (Text/HTML)
  ├── Task 5 (Image) — 需要 LLM Provider
  └── Task 6 (URL) — 依赖 Task 2/4/5 的转换器
      └── Task 7 (编排器) — 依赖所有转换器
          ├── Task 8 (HTTP 路由)
          └── Task 9 (CLI)
```

---

## 6. 关键设计决策

### 6.1 为什么不扩展现有 `pipeline/collector.py`？

现有 Collector 有三个硬耦合：
1. `EventBus.emit(EventName.COLLECTOR_DONE, ...)` — 事件总线
2. `enforce_permission(AgentType.COLLECTOR, ...)` — 权限系统
3. `SourceType` 枚举 — 类型系统

这些耦合使得 Collector 无法在 pipeline 外独立使用（如脚本、CLI、测试）。新建 `src/collector/` 模块保持零框架依赖，仅依赖 `utils/extract/` 的纯函数和 `llm/base.py` 的抽象接口。

### 6.2 为什么不直接复用 `services/files.py::upload_file`？

`upload_file` 只做"存文件到 raw/sources/"，不做格式转换。采集模块的核心价值是"任意输入 → Markdown"，这是 upload 不具备的。两者可互补：upload 存原始文件，collect 转换后存 Markdown。

### 6.3 图片处理的 LLM 依赖策略

```python
# 优先级：
# 1. 已配置的 LLM Provider（通过 ProviderRegistry 获取）
# 2. 环境变量中的 API Key（直接构造 OpenAI/Anthropic provider）
# 3. 降级：仅提取图片元数据（EXIF），不 OCR
```

### 6.4 写入策略：原始文件 vs 转换后的 Markdown

| 输入类型 | raw/sources/ 存什么 | 说明 |
|----------|---------------------|------|
| PDF | 转换后的 `.md` | 用户期望的是可编辑的文本 |
| DOCX | 转换后的 `.md` | 同上 |
| 图片 | 原始图片 + `.md` 描述文件 | 图片需要保留原件 |
| URL | 转换后的 `.md` | 网页内容会变化 |
| TXT/MD | 原始文件 | 已经是文本格式 |

---

## 7. 与现有模块的边界

```
┌─────────────────────────────────────────────────────────────┐
│  现有系统                                                    │
│  ┌─────────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ server/routes/   │  │ services/     │  │ pipeline/      │ │
│  │  ingest.py       │→│  ingest.py    │→│  collector.py  │ │
│  │  files.py        │  │  files.py     │  │  ingest.py     │ │
│  └─────────────────┘  └──────────────┘  └────────────────┘ │
│         ↑ upload              ↑ enqueue        ↑ LLM       │
└─────────│─────────────────────│────────────────│────────────┘
          │                     │                │
┌─────────│─────────────────────│────────────────│────────────┐
│  新模块  │                     │                │            │
│  ┌──────▼──────┐  ┌──────────▼──┐  ┌──────────▼──────────┐│
│  │ receiver/   │  │ converter/  │  │ writer/             ││
│  │ file/url    │→│ pdf/office  │→│ raw_writer.py       ││
│  │ /chat       │  │ /html/image │  │ (写 raw/sources/)   ││
│  └─────────────┘  └─────────────┘  └─────────────────────┘│
│                                                             │
│  依赖：utils/extract/ (复用) + llm/base.py (图片 OCR)      │
│  不依赖：EventBus, permissions, queue, project registry     │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| LLM Vision API 不可用 | 图片无法 OCR | 降级到元数据提取 + 提示用户手动描述 |
| 大文件内存溢出 | OOM | 流式处理，分块读取 |
| URL 抓取被反爬 | 内容为空 | 重试 + User-Agent 伪装 + 提示用户手动下载 |
| 格式转换丢失结构 | 信息不完整 | 保留原始文件 + 生成结构化 Markdown |
| 图片 OCR 准确率低 | 内容错误 | 多模型交叉验证（可选） |

---

## 9. 使用示例

### HTTP API

```bash
# 上传 PDF 文件
curl -X POST http://127.0.0.1:19828/api/v1/projects/$PROJECT/collect \
  -F "file=@paper.pdf"

# 抓取 URL
curl -X POST http://127.0.0.1:19828/api/v1/projects/$PROJECT/collect \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/article"}'

# 上传图片
curl -X POST http://127.0.0.1:19828/api/v1/projects/$PROJECT/collect \
  -F "file=@screenshot.png"
```

### Python API

```python
from src.collector import Collector

collector = Collector(project_root=Path("/path/to/project"), llm_provider=provider)

# PDF
result = await collector.collect("paper.pdf")

# URL
result = await collector.collect("https://example.com/article")

# 图片
result = await collector.collect("screenshot.png")

# bytes 输入
result = await collector.collect("upload.pdf", content=pdf_bytes)
```

### CLI

```bash
python -m src.cli collect <project_id> paper.pdf
python -m src.cli collect <project_id> https://example.com/article
python -m src.cli collect <project_id> screenshot.png
```
