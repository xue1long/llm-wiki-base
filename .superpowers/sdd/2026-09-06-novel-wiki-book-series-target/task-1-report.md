# Task 1 报告：书系 manifest 和兼容契约

## 改动文件

- `src/kc/views/book/wiki/series_model.py`：`series-manifest-v1` / book manifest 数据模型、canonical SHA-256、严格状态转移。
- `src/kc/views/book/wiki/series_validate.py`：schema、release 批次、文件哈希、hard/soft dependency 和 legacy 校验。
- `src/kc/views/book/wiki/__init__.py`：公共 API 导出。
- `src/services/files.py`：新增 `book_wiki_series_manifest`，优先读取已验证 release 内的 `series-manifest.json`，否则返回匿名单书兼容视图。
- `src/server/routes/files.py`：新增可选 `GET /api/v1/projects/{project_id}/book-wiki/series`。
- `tests/test_kc/test_book_series_manifest.py`：契约测试。

## RED / GREEN

RED：`TEMP/TMP/TMPDIR=.tmp-pytest PYTHONPATH=. <bundled-python> -m pytest --import-mode=importlib tests/test_kc/test_book_series_manifest.py -q` 无法启动，因为本机没有 `python`/`C:\Python314\python.exe`，可发现的 uv trampoline 返回 `permission denied (os error 5)`。

GREEN：`C:\Program Files\PostgreSQL\17\pgAdmin 4\python\python.exe -m py_compile src/kc/views/book/wiki/series_model.py src/kc/views/book/wiki/series_validate.py src/services/files.py src/server/routes/files.py` 通过。pytest 定向测试和回归测试受同一运行环境限制，未声称通过。

## 接口示例

```python
from src.kc.views.book.wiki import validate_series_manifest, transition_status

assert validate_series_manifest(payload)["ok"]
next_status = transition_status("draft", "partial")
```

`GET /book-wiki/series` 返回 series manifest；旧 `outline-v1` / 无 `series_id` release 返回 `legacy: true`、`series_id: null`、`book_id: null`，并保留可读状态和 books 形状。

## 兼容策略和 ruling

- 旧 release 不迁移、不猜测归属；只有明确写入的 `series_id` / `book_id` 才会被使用。
- 单书已有 API 字段未修改；series API 是新增可选入口。
- release 文件路径必须是 release 根下的单段相对路径；每个 `files` 条目按 SHA-256 校验。
- manifest digest 对 `manifest_sha256` / `canonical_digest` 字段自排除，避免自引用。
- hard dependency 必须指向存在且 `ready` 的书；空字符串、缺失目标和非 ready 目标均失败。soft dependency 缺失只进入 `soft_missing`。
- Ruling：series manifest 若缺失，兼容端点按单书匿名视图返回，而不是生成猜测的 `series_id`；这保留旧 UI 可读性并满足 fail-closed 归属边界。

## 已知限制

- 本 Task 未把 manifest 写入现有 compiler 发布流程；后续 Task 负责书系编译与原子指针发布接入。
- 当前哈希 API 校验 manifest `files` 映射，调用方需把 outline、sidecar、正文列入映射。
- pytest 因宿主 Python 权限问题未执行。

## 修复追加

首轮定向 pytest 由协作环境发现 round-trip 失败：输入未提供的可选空 `hashes` 被序列化回 payload。修复为仅序列化非空可选字段；必需字段仍始终输出，校验语义不变。修复后应重跑本测试及相关 book/files 回归。
