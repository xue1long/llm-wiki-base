# ruflo-kb/src/utils/extract/office.py
from pathlib import Path

def extract_office_text(file_path: str) -> str:
    """从 Office 文档提取文本"""
    ext = Path(file_path).suffix.lower()

    if ext in [".docx", ".doc"]:
        return extract_docx_text(file_path)
    elif ext in [".xlsx", ".xls"]:
        return extract_xlsx_text(file_path)
    else:
        raise ValueError(f"Unsupported office format: {ext}")

def extract_docx_text(file_path: str) -> str:
    """从 DOCX 提取文本"""
    from docx import Document
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)

def extract_xlsx_text(file_path: str) -> str:
    """从 XLSX 提取文本"""
    from openpyxl import load_workbook
    wb = load_workbook(file_path, data_only=True)
    parts = []

    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                parts.append("\t".join(cells))

    return "\n".join(parts)
