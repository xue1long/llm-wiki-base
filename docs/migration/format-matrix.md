# Canonical adapter format matrix

| Format | Existing converter | KC adapter status | Evidence定位 | Next gate |
|---|---|---|---|---|
| Markdown/TXT | `TextConverter` | verified | paragraph block | C-05 passed |
| URL/HTML | `UrlConverter` / `HtmlConverter` | verified | extracted text block | HTML regression passed |
| SRT/VTT | `LegacyCollector` transcript cleanup | verified | subtitle text block | timestamp cleanup regression passed |
| PDF | `PdfConverter` | smoke verified | page/text block; page markers preserved by converter | add text-bearing PDF fixture |
| DOCX | `OfficeConverter` | smoke verified | paragraph block | add malformed-file assertion (done) |
| XLSX | `OfficeConverter` | smoke verified | sheet/row block | add malformed-file assertion (done) |

KC reuses the existing converters. A format is not considered fully migrated until it has a real sample, a failure sample, and an Evidence定位 test.
