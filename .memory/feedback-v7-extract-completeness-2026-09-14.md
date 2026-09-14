# V7 extract Stage 1/3 收尾（2026-09-14）

- 修复 `doc_classifier` 的三个失败：`pytest.param` 不能直接按二元组解包，`filename_hint` 必须先于短文本 incomplete 判断。
- 新增 `src/pipeline/v7_extract/completeness_checker.py`：按文档类型长度门槛、标题承诺数量与实际结构数量、intro-only 和显式 incomplete 标记进行 fail-closed 检测；可选 LLM 仅作为启发式拒绝后的 mock 兜底。
- 新增完整性检测器测试，覆盖 7 个 fixture、空/纯标题/短引言、数量缺口、超长文本和 LLM fallback。
- 验证：V7 三个测试文件 `32 passed, 2 skipped`；`tests/test_pipeline/` `644 passed, 2 skipped, 43 warnings`；目标文件 `py_compile` 通过。
- 环境注意：普通 sandbox 下 `pytest` 用户 site 不可见，使用已批准的 escalated Python 环境运行测试；`graphify query/update` 仍被本机 uv trampoline canonicalization 错误阻塞。
