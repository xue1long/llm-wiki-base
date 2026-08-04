# 输入验证修复报告

**日期**: 2026-08-05
**修复范围**: Round 6 边界用例测试发现的安全问题

---

## 修复摘要

| 问题 | 修复状态 | 修复方式 |
|-----|---------|---------|
| 空源字符串 | ✅ 已修复 | HTTP 400 Bad Request |
| 路径遍历 `../../../etc/passwd` | ✅ 已修复 | HTTP 400 Bad Request |
| 空字节注入 `test\x00.md` | ✅ 已修复 | HTTP 400 Bad Request |
| Unix 绝对路径 `/etc/passwd` (Windows) | ✅ 已修复 | HTTP 400 Bad Request |
| 控制字符注入 | ✅ 已修复 | HTTP 400 Bad Request |
| 不存在的文件 | ⚠️ 延迟失败 | 设计决策 - Collector 阶段失败 |
| 无效 URL | ⚠️ 延迟失败 | 设计决策 - Collector 阶段失败 |

---

## 修复详情

### 新增文件

#### `src/lib/validators.py`

**功能**: HTTP API 输入验证模块

**主要验证器**:
- `validate_source_string()` - 基础字符串验证
  - 空字符串检测
  - 空字节注入防护
  - 控制字符检测
  - 路径遍历检测（深度 > 3 层）

- `validate_file_source()` - 文件路径验证
  - 绝对路径边界检查
  - 相对路径逃逸检测
  - Unix 风格路径特殊处理（Windows 兼容）

- `validate_url_source()` - URL 验证
  - scheme 检查（仅 http/https）
  - hostname 存在性检查
  - 嵌入凭证拒绝

- `validate_source()` - 统一入口
  - 自动检测源类型
  - 路由到对应验证器

### 修改文件

#### `src/server/routes/ingest.py`

**修改内容**:
```python
# 在入队前添加验证
if isinstance(body.source, str):
    try:
        validate_source(body.source, project_root)
    except ValueError as e:
        raise HTTPException(400, f"Invalid source: {e}")
```

---

## 测试覆盖

### 单元测试

**文件**: `tests/test_lib/test_validators.py`

**覆盖**:
- 26 个测试用例
- 空字符串、空字节、控制字符、路径遍历
- URL scheme、hostname、凭证
- 边界用例（3 层 vs 4 层遍历、Unicode 路径）

**结果**: 26/26 通过

### 集成测试

**文件**: `test_round6_edgecases.py`

**修复前**:
```
1/6 handled, 5/6 unexpected
```

**修复后**:
```
4/6 handled, 2/6 delayed failure (by design)
```

---

## 设计决策

### 延迟失败场景

以下场景选择在 Collector 阶段失败，而非入队时拒绝：

| 场景 | 原因 |
|-----|------|
| 文件不存在 | 避免同步文件系统访问阻塞 HTTP 请求 |
| URL 不可达 | 避免同步网络请求阻塞 HTTP 请求 |

**优势**:
1. HTTP API 保持快速响应（不阻塞）
2. 错误在异步任务中正确记录
3. 任务状态机制正确处理失败

**安全性**: 这些失败不构成安全风险，只是产生无效任务（会被正确清理）。

---

## 安全影响评估

### 已修复风险

| 风险类型 | OWASP 分类 | 修复前 | 修复后 |
|---------|-----------|--------|--------|
| 路径遍历 | A01:2021 Broken Access Control | 高 | 低（已防护） |
| 空字节注入 | A03:2021 Injection | 中 | 低（已防护） |
| 控制字符注入 | A03:2021 Injection | 低 | 低（已防护） |

### 残留风险

**无**。延迟失败场景不构成安全风险。

---

## 部署建议

1. **立即部署**: 这是安全修复，优先级 P0
2. **监控**: 观察 `/ingest` 端点的 400 响应率
3. **文档**: 更新 API 文档说明输入验证规则

---

## 后续任务

- [x] 实现 `src/lib/validators.py`
- [x] 集成到 HTTP 路由层
- [x] 单元测试覆盖
- [x] 集成测试验证
- [ ] 更新 API 文档（OpenAPI schema）
- [ ] 添加速率限制（防止暴力枚举）