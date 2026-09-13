# Task 5 review

## Scope

只读检查了：

- `.superpowers/sdd/2026-09-08-unified-book-llm-pipeline/task-5-brief.md`
- `.superpowers/sdd/2026-09-08-unified-book-llm-pipeline/task-5-report.md`
- `src/cli_ext/project_cmd.py`
- `docs/adr/2026-09-08-unified-book-llm-pipeline.md`
- `docs/adr/INDEX.md`
- `tests/test_cli_ext/test_cmd_project.py`

未修改生产代码，未提交。

## Spec verdict

**PASS**

依据：

- 新项目初始化写入项目根目录 `book.rules.md`。
- 模板只说明项目需要自行填写读者、用途、语气、结构等编辑意图，没有预设具体项目风格。
- 初始化路径没有创建或修改 `.llm-wiki/policy.json`；focused test 也检查了该文件不存在。
- ADR 明确既有项目需要显式迁移，并明确本阶段只覆盖 `book build-from-wiki`，不覆盖 legacy `book build`。
- 变更没有触碰 compiler、preflight 或 LLM provider 行为，符合 Task 5 的“bootstrap and durable docs”边界。

## Quality verdict

**PASS，带验证限制**

实现很小，复用了现有 scaffold 写入路径，没有引入规则解析器、授权抽象或新的运行时框架。ADR、索引和实现报告的范围基本一致。

实现报告记录 focused test `7 passed`；本次复核尝试重跑同一测试时，当前环境没有可用的 `python` 命令，`.venv` 的 uv trampoline 又因权限错误无法启动，因此无法独立复现该结果。`git diff --check` 通过。

## Critical findings

None.

## Important findings

None.

## Minor findings

1. focused test 对“中性、无授权语义”的验证仍偏弱：目前断言包含 `authorization`，但没有明确断言模板不包含 `external_llm_allowed`、`content_export_authorized` 或类似的授权肯定语句。代码本身没有发现该问题，但测试没有完全锁住需求边界。

## 建议的最小修复

仅补强 `tests/test_cli_ext/test_cmd_project.py` 的断言即可：在保留 policy 文件不存在检查的同时，断言生成的 `book.rules.md` 不包含 `external_llm_allowed`、`content_export_authorized` 和明确的外部 LLM 授权语句。无需修改生产代码、编译器或 ADR。

