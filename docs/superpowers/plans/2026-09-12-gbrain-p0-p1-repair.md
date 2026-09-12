# GBrain hybrid 试点 P0/P1 修复计划

## 目标

修复真实 GBrain 能力验证发现的阻断问题，使“GBrain MCP 可选 hybrid 搜索试点”具备可验证的启用、导入、搜索和运行时安全闭环。

## 并行切片

### A：真实状态契约与 P0 ready 门禁

- 修改：`src/integrations/gbrain/worker.py`
- 测试：`tests/test_integrations/test_gbrain_worker.py`
- 修复真实 GBrain `embed_coverage_pct` 字段解析。
- 增加真实 JSON 形状回归测试，确保未达到 100% 时 fail-closed。

### B：初次导入边界与 source 幂等

- 修改：`src/integrations/gbrain/api.py`、`src/integrations/gbrain/sync.py`
- 测试：`tests/test_integrations/test_gbrain_project.py`、`tests/test_integrations/test_gbrain_sync.py`
- 让 snapshot 和实际 import 使用同一份可搜索 Markdown 页面集合。
- 排除 `_archive`、`_stubs`、`.index`、Book 和非 Markdown 文件。
- rebuild/重试时复用本项目已拥有的 source，避免重复 `sources add`。

### C：运行时安全与可修复安装

- 修改：`src/integrations/gbrain/runtime.py`、`src/integrations/gbrain/setup.py`
- 测试：`tests/test_integrations/test_gbrain_runtime.py`、`tests/test_integrations/test_gbrain_setup.py`
- 限制 managed ref/path，防止路径穿越。
- 增加 managed 安装互斥和安全临时目录提升。
- 让“修复”能够替换损坏运行时，但仍保持 reviewed ref、来源和校验门禁。

## 合并后串行切片

### D：增量同步闭环

- 触发 Wiki 新增、修改、删除、恢复后的 reconcile。
- 只有 MCP 操作成功后更新 manifest；失败保持可重试状态。
- 增加恢复语义和端到端回归测试。

### E：统一验证

- GBrain 专项测试、编译检查、WebUI 语法检查、应用 smoke test。
- 真实外部 GBrain `sources status --json` 与 MCP initialize/search 验证。
- 最终代码审查，确认 P0/P1 无遗留。

## 验收门槛

1. 真实 GBrain source 状态能够正确转换为本地 coverage。
2. 归档页和存根页不会进入 GBrain。
3. 同一项目重复 enable/rebuild 不因 source 重复注册失败。
4. 运行时只能来自明确配置或受控托管目录。
5. Wiki 变更后远端索引最终与本地 manifest 一致。
6. 所有新增回归测试先红后绿，专项验证通过。
