# Task 2 follow-up report

## Scope

仅修改 `tests/test_cli_ext/test_book_build_from_wiki_modes.py`，处理 Task 2 评审指出的测试 seam 问题；未修改生产代码。

## Changes

- `_parse()` 在 `parse_args()` 后显式执行 `args.validate(args, parser)`，与 `src/cli.main` 的校验路径一致。
- 默认模式、旧参数冲突、`--plan/--preview/--apply` 互斥测试现在经过真实 validate hook。
- 旧参数对 `--use-llm --polish` 增加 `build_mode == "preview"` 断言。

## Verification

目标测试命令：

```text
uv run --no-sync python -m pytest tests/test_cli_ext/test_book_build_from_wiki_modes.py --import-mode=importlib -q
```

结果：BLOCKED。uv 无法初始化默认缓存目录；改用临时 `UV_CACHE_DIR` 后，仍因查询 Python 解释器时收到 Windows `拒绝访问。 (os error 5)` 而无法启动测试。

已完成静态检查：测试 helper 调用的 `validate(args, parser)` 与 `src/cli.main` 相同，且仅涉及目标测试文件。

