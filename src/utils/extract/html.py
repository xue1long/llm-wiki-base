# ruflo-kb/src/utils/extract/html.py
import re

def convert_html_tables_to_markdown(html: str) -> str:
    """HTML 表格转 Markdown"""
    def parse_table(table_content: str) -> str:
        rows = re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", table_content, re.IGNORECASE)
        if not rows:
            return ""

        parsed_rows = []
        for row in rows:
            cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row, re.IGNORECASE)
            cells = [
                re.sub(r"<[^>]+>", "", c).strip()
                for c in cells
            ]
            parsed_rows.append(cells)

        if not parsed_rows:
            return ""

        header = f"| {' | '.join(parsed_rows[0])} |"
        separator = f"| {' | '.join(['---'] * len(parsed_rows[0]))} |"
        body = "\n".join(f"| {' | '.join(row)} |" for row in parsed_rows[1:])

        return f"{header}\n{separator}\n{body}"

    tables = re.findall(r"<table[^>]*>([\s\S]*?)</table>", html, re.IGNORECASE)
    result = html

    for table in tables:
        md_table = parse_table(table)
        if md_table:
            result = result.replace(f"<table>{table}</table>", md_table, 1)

    return result

def html_img_tags_to_markdown(html: str, base_url: str = "") -> str:
    """HTML img 标签转 Markdown"""
    def replace_img(match_obj):
        tag = match_obj.group(0)
        src_match = re.search(r'src=["\']([^"\']+)["\']', tag)
        alt_match = re.search(r'alt=["\']([^"\']*)["\']', tag)
        src = src_match.group(1) if src_match else ""
        alt = alt_match.group(1) if alt_match else ""
        full_src = src if src.startswith("http") else base_url + src
        return f"![{alt}]({full_src})"

    return re.sub(r"<img[^>]+>", replace_img, html, flags=re.IGNORECASE)
