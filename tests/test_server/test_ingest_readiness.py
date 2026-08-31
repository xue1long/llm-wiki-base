"""The service entry used by HTTP/queue ingestion shares the pre-Analyzer gate."""

from __future__ import annotations

from src.services.ingest import run_ingest_pipeline
from src.wiki.core.paths import WikiPaths
from src.wiki.storage.ensure import ensure_knowledge_base


class ProviderMustNotBeCalled:
    def __getattr__(self, name):
        raise AssertionError(f"provider called for blocked source: {name}")


def test_service_ingest_entry_returns_no_pages_for_blocked_source(tmp_path) -> None:
    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    source = paths.raw_sources / "navigation.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    text = "登录/注册\n登录/注册\n05_题材专题"
    source.write_text(text, encoding="utf-8")

    pages = run_ingest_pipeline(
        paths,
        source,
        text,
        ProviderMustNotBeCalled(),
        task_id="service-readiness-test",
    )

    assert pages == []
