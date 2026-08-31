from __future__ import annotations

import pytest

from src.pipeline.extraction_types import SourceRange, artifact_from_text
from src.pipeline.specialists import SpecialistError, run_specialist


def test_table_specialist_preserves_text_and_ranges() -> None:
    artifact = artifact_from_text(
        "列一\t列二\n值一\t值二",
        source_id="raw/table-specialist.xlsx",
        format="xlsx",
        extraction_method="xlsx_cells",
        ranges=(
            SourceRange("table_row", 0, 5, 0),
            SourceRange("table_row", 0, 5, 1),
        ),
    )

    result = __import__("asyncio").run(run_specialist("table", artifact))

    assert result == artifact


@pytest.mark.asyncio
async def test_ocr_specialist_failure_is_typed_and_bounded() -> None:
    artifact = artifact_from_text(
        "",
        source_id="raw/ocr-specialist.png",
        format="image",
        extraction_method="ocr",
        extraction_errors=("OCR extractor unavailable",),
    )

    with pytest.raises(SpecialistError, match="specialist_failed") as exc_info:
        await run_specialist("ocr", artifact)

    assert exc_info.value.route == "ocr"
    assert exc_info.value.attempts == 1


@pytest.mark.asyncio
async def test_specialist_second_attempt_is_rejected() -> None:
    artifact = artifact_from_text(
        "识别结果",
        source_id="raw/ocr-specialist-once.png",
        format="image",
        extraction_method="ocr",
        ranges=(SourceRange("image_region", 0, 4, 0),),
    )

    await run_specialist("ocr", artifact)
    with pytest.raises(SpecialistError, match="one attempt"):
        await run_specialist("ocr", artifact)
