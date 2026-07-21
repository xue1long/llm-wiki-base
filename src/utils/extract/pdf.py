# ruflo-kb/src/utils/extract/pdf.py
from pypdf import PdfReader

def extract_pdf_text(file_path: str) -> str:
    """从 PDF 提取文本"""
    reader = PdfReader(file_path)
    text_parts = []

    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)

    return "\n\n".join(text_parts)
