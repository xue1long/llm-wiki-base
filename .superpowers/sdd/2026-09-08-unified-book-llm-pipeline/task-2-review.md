# Task 2 review — CLI mode contract

## Spec verdict

**部分通过，不能验收。**

生产 CLI 的实际 `main()` 路径会执行 `validate` 钩子，因而默认模式会被归一为 `plan`，`preview/apply` 会转发为 LLM 正文润色，三种正式模式也由 argparse 互斥组约束。旧的单独 `--use-llm` 或 `--polish` 在实际 CLI 校验中会被拒绝，旧参数对会映射为 `preview`。

但指定的新增测试没有执行这个 `validate` 钩子：`_parse()` 只调用 `build_parser().parse_args(...)`。因此在当前源码下，省略模式得到的仍是 `build_mode=None`，单个旧 LLM 参数也不会被拒绝。测试文件本身不能证明需求已满足，且按现状至少有 3 个测试会失败。

## Quality verdict

**Important 问题。** 主要问题是测试 seam 选错，导致测试绕过了真实 CLI 的模式归一化边界；生产改动没有发现必然的发布路径回归。当前报告中的“7 passed”与现有测试代码不一致，无法作为本地验收证据。

## Critical findings

None.

## Important findings

1. **模式校验没有被测试调用。**

   位置：`tests/test_cli_ext/test_book_build_from_wiki_modes.py:15-18`。

   `_parse()` 只调用 `parse_args()`，而模式默认、旧参数冲突检查和旧参数对映射都写在 `src/cli.py:604-619` 的 `validate` 回调中；真正的 `main()` 直到 `src/cli.py:674-676` 才调用它。

   直接后果：

   - `test_default_mode_is_plan` 看到的是 `None`，不是 `plan`；
   - `test_plan_rejects_legacy_llm_flags` 的两个参数不会抛出 `SystemExit`；
   - 测试没有验证旧参数对映射为 `preview`，也没有验证 `narrative` 的模式限制。

   最小修复是让测试 helper 在 `parse_args()` 后调用 `args.validate(args, parser)`，不需要改生产逻辑。另应补一个断言确认旧参数对最终得到 `build_mode == "preview"`。

## Minor findings

1. `src/cli.py:572` 和 `src/cli.py:600-601` 的帮助文本仍说 `--encyclopedic` / `--narrative` requires `--use-llm`，但新的公开契约实际要求 `--preview` 或 `--apply`。

2. `src/cli_ext/book_cmd.py:168-172` 的结构化错误已经使用新模式文案，但非 JSON 错误仍输出 `--use-llm`，用户会得到前后不一致的提示。

3. `src/cli_ext/book_cmd.py:202-207` 的参数缩进多了一个空格。它不影响运行，但属于本次改动留下的可读性问题。

## 建议的最小修复

1. 只修改测试 helper：解析后执行该 Namespace 上的 `validate` 回调，再返回已归一化的参数；同时断言旧参数对映射为 `preview`。
2. 更新两处 CLI help 和一处非 JSON 错误文本为 `--preview/--apply`。
3. 保留 `cmd_book_build_from_wiki()` 的三态转发映射；不扩展到 compiler/preflight，也不改变旧的直接 Python caller 兼容分支，除非另有任务要求禁止所有旧 Namespace 的 outline-only 行为。

## Verification status

- 已读取需求文件和实现报告。
- 已限定检查 `src/cli.py`、`src/cli_ext/book_cmd.py`、`tests/test_cli_ext/test_book_build_from_wiki_modes.py`。
- 未修改生产代码，未提交。
- 本机 Python 不在 PATH，无法重新运行 pytest；上述测试失败结论来自 parser/validate 调用链的静态核查。
