# Task 1 收尾报告：发布闭包 fail-closed

## 结果

Task 1 已按 brief 完成静态收尾。`check_default_closure(obj, integrity_report=None) -> ClosureReport` 接口保持不变；发布闭包不再通过 assumed/simplified 路径放行。

## 实现与审查结论

- `hard_gates_passed` 仅在实际传入的 IntegrityReport 同时满足 `passed=true`、`blocked=false` 时为 true；最终 `ClosureReport.passed` 同时要求闭包条件和硬门槛通过。
- 缺失 IntegrityReport：`context_resolution_not_unresolved.details = missing_integrity_report`。
- 缺失 Evidence：`all_evidence_status_active.details = missing_evidence`。
- synthesized 对象缺 `synthesis_provenance`、`derived_from` 或 approval：`synthesized_full_provenance.details = missing_provenance`。
- concept、claim、evidence 或 source-trust 依赖状态缺失/不可发布：对应条件失败并返回 `dependency_not_publishable`。
- 旧测试 fixture 已补齐最小 concept、evidence、source-trust 状态快照及通过的 IntegrityReport，未削弱 fail-closed 契约。
- `IntegrityGate.check_default_closure()` 保留“未显式提供报告时先执行 11 Gate”的既有行为，并同步更新契约说明。

## 静态验证

- 已完整阅读 Task 1 brief、主计划 Task 1、`closure.py`、`orchestrator.py`、相关测试和全部调用点。
- 已静态核对四个稳定 reason code 均由生产代码返回，并由 fail-closed 测试逐项断言。
- 已静态核对通过 fixture 的依赖快照完整，失败 fixture 每项只移除或破坏目标依赖。
- `rg` 检查确认生产结果 details 中不再包含 `assumed` 或 `simplified`；这两个词只保留在测试的反向断言中。
- `git diff --check` 返回 0；仅有仓库现存的 LF/CRLF 转换提示，无 whitespace error。
- 未运行 Python 或 pytest，遵循本次接管指令。因此本报告只提供静态验证结论，不声明运行时测试通过。

## 提交范围

仅提交以下 Task 1 文件：

- `src/kc/integrity/closure.py`
- `src/kc/integrity/orchestrator.py`
- `tests/test_kc/test_default_closure.py`
- `tests/test_kc/test_closure_fail_closed.py`
- `.superpowers/sdd/2026-08-29-kc-integrity-idempotency-layered/task-1-report.md`

提交信息：`fix(kc): make publication closure fail closed`

工作区中不属于 Task 1 允许提交范围的未跟踪计划文件保持未暂存、未修改。
