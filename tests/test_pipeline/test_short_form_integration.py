"""Integration tests for short-form template and routing."""
from pathlib import Path


from src.pipeline.generator import (
    _render_short_form_template_section,
    _load_short_form_template,
    _render_page_body,
)
from src.wiki.core.types import PageType
from src.wiki import WikiPaths
from src.wiki.templates.types import Template
from src.wiki.templates.renderer import render_body


# ---------------------------------------------------------------------------
# Test 1: short-form.md exists and has correct header
# ---------------------------------------------------------------------------

def test_short_form_template_loadable():
    """src/wiki/templates/bundled/short-form.md exists with valid header."""
    template_path = Path("src/wiki/templates/bundled/short-form.md")
    assert template_path.exists(), f"Missing: {template_path}"
    content = template_path.read_text(encoding="utf-8")
    assert "<!-- wiki-template-version: 2.0.0 -->" in content
    # Q23: must use concept type (passes parser validation)
    assert "<!-- wiki-template-type: concept -->" in content
    assert "<!-- slot:summary -->" in content
    assert "<!-- slot:key_points -->" in content
    assert "<!-- slot:references -->" in content


# ---------------------------------------------------------------------------
# Test 2: _render_short_form_template_section returns prompt section
# ---------------------------------------------------------------------------

def test_render_short_form_template_section_returns_template():
    """Function returns string with '### short-form' marker and slot markers."""
    project_root = Path.cwd()
    section = _render_short_form_template_section(project_root)
    assert "### short-form" in section
    assert "<!-- slot:summary -->" in section
    assert "<!-- slot:key_points -->" in section
    assert "<!-- slot:references -->" in section


# ---------------------------------------------------------------------------
# Test 3: _load_short_form_template returns raw body
# ---------------------------------------------------------------------------

def test_load_short_form_template_returns_body():
    """Function returns raw template body without prompt '###' prefix."""
    project_root = Path.cwd()
    body = _load_short_form_template(project_root)
    # body has no ### prefix (that's for prompt injection)
    assert "### short-form" not in body
    # but has the template header
    assert "<!-- wiki-template-type: concept -->" in body
    assert "<!-- slot:summary -->" in body


# ---------------------------------------------------------------------------
# Test 4: render_body works with short-form template + CONCEPT page_type
# (Q23 critical: must not raise TemplateParseError)
# ---------------------------------------------------------------------------

def test_short_form_renders_with_concept_page_type(tmp_path):
    """render_body with page_type=CONCEPT + short-form template does not raise."""
    paths = WikiPaths(root=tmp_path)
    body = _load_short_form_template(paths.root)
    slots = {
        "summary": "这是摘要",
        "key_points": "这是核心观点",
        "references": "- 来源1",
    }
    rendered = render_body(
        template_body=body,
        slots=slots,
        page_type=PageType.CONCEPT,
        template_version="2.0.0",
    )
    assert "这是摘要" in rendered
    assert "这是核心观点" in rendered
    # short-form slots are the only ones filled
    assert "<!-- slot:" not in rendered  # all markers replaced


# ---------------------------------------------------------------------------
# Test 5: _render_page_body routes to short-form when hint=memory
# ---------------------------------------------------------------------------

def test_render_page_body_uses_short_form_on_memory_hint(tmp_path):
    """hint=memory + page_type=CONCEPT triggers short-form.md rendering."""
    paths = WikiPaths(root=tmp_path)
    # Create a fake resolved template (unused but required for type signature)
    template = Template(
        type=PageType.CONCEPT,
        body_markdown="<!-- wiki-template-version: 2.0.0 -->\n## UNUSED\n<!-- slot:unused -->",
        version="2.0.0",
        source="bundled",
        path=Path("dummy"),
    )
    slots = {
        "summary": "memory-summary",
        "key_points": "memory-points",
        "references": "- ref1",
    }
    body = _render_page_body(
        template=template,
        slots=slots,
        page_type=PageType.CONCEPT,
        paths=paths,
        processing_depth_hint="memory",
    )
    # short-form template has '## 摘要' section
    assert "memory-summary" in body
    assert "memory-points" in body
    assert "## 摘要" in body or "摘要" in body


# ---------------------------------------------------------------------------
# Test 6: _render_page_body falls back when short-form missing
# ---------------------------------------------------------------------------

def test_render_page_body_falls_back_on_missing_short_form(tmp_path, monkeypatch):
    """short-form.md missing → fallback to template.body_markdown, no crash."""
    paths = WikiPaths(root=tmp_path)
    template = Template(
        type=PageType.CONCEPT,
        body_markdown=(
            "<!-- wiki-template-version: 2.0.0 -->\n"
            "<!-- wiki-template-type: concept -->\n"
            "\n"
            "## fallback-heading\n"
            "<!-- slot:unused -->\n"
        ),
        version="2.0.0",
        source="bundled",
        path=Path("dummy"),
    )

    # Monkey-patch _load_short_form_template to raise FileNotFoundError
    from src.pipeline import generator as gen_module

    def raise_fnf(_root):
        raise FileNotFoundError("simulated missing")

    monkeypatch.setattr(gen_module, "_load_short_form_template", raise_fnf)

    slots = {"unused": "fallback-content"}
    body = _render_page_body(
        template=template,
        slots=slots,
        page_type=PageType.CONCEPT,
        paths=paths,
        processing_depth_hint="memory",
    )
    # Falls back to template.body_markdown rendering
    assert "fallback-content" in body
    assert "fallback-heading" in body


# ---------------------------------------------------------------------------
# Test 7 (bonus): hint=None keeps existing behavior
# ---------------------------------------------------------------------------

def test_render_page_body_no_hint_uses_template(tmp_path):
    """hint=None → use template.body_markdown, not short-form."""
    paths = WikiPaths(root=tmp_path)
    template = Template(
        type=PageType.CONCEPT,
        body_markdown=(
            "<!-- wiki-template-version: 2.0.0 -->\n"
            "<!-- wiki-template-type: concept -->\n"
            "\n"
            "## default-heading\n"
            "<!-- slot:unused -->\n"
        ),
        version="2.0.0",
        source="bundled",
        path=Path("dummy"),
    )
    slots = {"unused": "default-content"}
    body = _render_page_body(
        template=template,
        slots=slots,
        page_type=PageType.CONCEPT,
        paths=paths,
        processing_depth_hint=None,
    )
    assert "default-content" in body
    assert "default-heading" in body
