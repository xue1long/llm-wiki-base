# ruflo-kb/src/utils/text.py
import re

MARKDOWN_CHUNK_SIZE = 500
MARKDOWN_CHUNK_OVERLAP = 50

def trim_text(text: str) -> str:
    """清洗文本：移除多余空白"""
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def html_to_text(html: str) -> str:
    """HTML 转纯文本"""
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def chunk_markdown(content: str, chunk_size: int = MARKDOWN_CHUNK_SIZE) -> list[str]:
    """将 Markdown 内容分块"""
    if len(content) <= chunk_size:
        return [content]

    chunks = []
    paragraphs = content.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # 保留最后几行作为重叠
            last_lines = current_chunk.split("\n")[-3:]
            current_chunk = "\n".join(last_lines) + "\n" + para
        else:
            current_chunk += ("\n\n" if current_chunk else "") + para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    # 如果只有一个chunk但仍然超过chunk_size，按字符数强制分割
    if len(chunks) == 1 and len(chunks[0]) > chunk_size:
        chunks = [chunks[0][i:i+chunk_size] for i in range(0, len(chunks[0]), chunk_size)]

    return chunks
