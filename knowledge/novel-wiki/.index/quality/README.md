# novel-wiki Wiki 质量基线与体检报告

本目录存放 wiki-repair-novel-wiki.md 修复方案执行过程中产生的**只读**质量数据：

```text
quality/
├── baseline-YYYYMMDD.json   # 综合基线报告（规模/结构/关系/链接/索引/内容）
├── baseline-YYYYMMDD.md     # 基线报告人类可读版
├── baseline-YYYYMMDD.txt    # validate_novel_wiki_frontmatter.py 原始输出
├── duplicate-frontmatter-YYYYMMDD.txt
├── dangling-relations-YYYYMMDD.json
├── broken-wikilinks-YYYYMMDD.json
├── duplicate-titles-YYYYMMDD.json
└── iso-timestamps-YYYYMMDD.json
```

## 约定

- **本目录不属于源数据**：所有文件都是 `scripts/*.py` 的只读产出，可随时删除重建
- **git 默认忽略本目录**（`.index/*` 规则），但 README.md 通过例外白名单入 git
- **历史基线不被覆盖**：每次体检产出新文件，老文件保留用于 diff 对比
- **删除影响**：删除本目录不影响 wiki/ 内容，但下次体检需要重新扫描

## 与方案对应

| 文件 | 对应方案章节 |
|---|---|
| baseline-YYYYMMDD.{json,md} | §2.1（生成全量统计）|
| duplicate-frontmatter-*.txt | §3.1（重复 Frontmatter 清理）|
| iso-timestamps-*.json | §3.2（时间戳规范化）|
| dangling-relations-*.json | §4.4（断链处理）|
| broken-wikilinks-*.json | §4.4 |
| duplicate-titles-*.json | §6（重复页面治理）|

## 相关脚本

- `scripts/validate_novel_wiki_frontmatter.py` — V4 8 键白名单校验
- `scripts/backup_wiki_file.py` — 幂等备份工具
- `scripts/check_duplicate_frontmatter.py`（待 T-B2 创建）
- `scripts/scan_dangling_relations.py`（待 T-B3 创建）
- `scripts/scan_broken_wikilinks.py`（待 T-B4 创建）
- `scripts/scan_duplicate_titles.py`（待 T-B5 创建）
- `scripts/scan_iso_timestamps.py`（待 T-B6 创建）
- `scripts/build_quality_baseline.py`（待 T-B7 创建）
