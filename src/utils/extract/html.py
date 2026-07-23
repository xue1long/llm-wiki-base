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

    # Use re.sub with a callback so tables with attributes
    # (e.g. <table class="data">) are still converted. The previous
    # string.replace approach only matched the bare form `<table>...</table>`,
    # silently dropping any table that had attributes.
    pattern = re.compile(r"<table[^>]*>([\s\S]*?)</table>", re.IGNORECASE)

    def _convert(match: re.Match) -> str:
        inner = match.group(1)
        md_table = parse_table(inner)
        return md_table if md_table else match.group(0)

    return pattern.sub(_convert, html)

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
