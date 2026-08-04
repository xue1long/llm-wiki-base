# Round 6 安全问题报告：HTTP API 输入验证缺失

## 问题概述

Round 6 边界测试发现 HTTP `/ingest` 端点**缺乏输入验证**，以下恶意/无效输入全部被接受并排队处理：

| 测试用例 | 预期行为 | 实际行为 | 风险等级 |
|---------|---------|---------|---------|
| 空源字符串 | 400 Bad Request | 200 queued | **中** - 无效任务 |
| 不存在的文件 | 404 Not Found | 200 queued | **低** - 后续失败 |
| 无效 URL | 400 Bad Request | 200 queued | **低** - 后续失败 |
| 路径遍历 `../../../etc/passwd` | 403 Forbidden | 200 queued | **高** - 安全风险 |
| 空字节注入 `test\x00.md` | 400 Bad Request | 200 queued | **高** - 安全风险 |

## 根本原因

`src/server/routes/ingest.py` 的路由处理器：

```python
@router.post("/projects/{project_id}/ingest")
async def ingest(body: IngestRequest, project_id: str):
    # 缺少输入验证！
    return await services.ingest.enqueue_source(project_id, body.source)
```

服务层 `src/services/ingest.py` 也没有同步验证。

## 建议修复

### 修复点 1：路由层验证（快速失败）

```python
# src/server/routes/ingest.py
from src.lib.validators import validate_source_path

@router.post("/projects/{project_id}/ingest")
async def ingest(body: IngestRequest, project_id: str):
    # 验证源字符串
    if not body.source or not body.source.strip():
        raise HTTPException(status_code=400, detail="Source cannot be empty")

    # 检测路径遍历
    if ".." in body.source or "\x00" in body.source:
        raise HTTPException(status_code=400, detail="Invalid source path")

    # 验证文件存在性（同步，不阻塞）
    if not body.source.startswith(("http://", "https://")):
        if not await validate_source_path(body.source, project_id):
            raise HTTPException(status_code=404, detail="Source file not found")

    return await services.ingest.enqueue_source(project_id, body.source)
```

### 修复点 2：服务层验证

```python
# src/services/ingest.py
async def enqueue_source(project_id: str, source: str) -> dict:
    # 双重验证（防御性）
    if not is_valid_source(source):
        raise ValueError(f"Invalid source: {source!r}")

    # ... existing logic
```

## 优先级

**P0 - Critical**：路径遍历和空字节注入是 OWASP Top 10 漏洞，必须在公开服务前修复。

## 影响范围

- 仅影响 HTTP API 入队阶段
- 不影响已运行的流水线（Collector 会失败并记录）
- 不影响 CLI 直接调用（有完整验证）

## 下一步

1. 创建 `src/lib/validators.py` 模块
2. 实现路径安全验证函数
3. 集成到 HTTP 路由层
4. 更新测试覆盖边界用例