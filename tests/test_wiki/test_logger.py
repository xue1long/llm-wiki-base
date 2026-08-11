from src.wiki.features.logger import log_event, read_log
from src.wiki.storage.ensure import ensure_knowledge_base
from src.wiki.core.paths import WikiPaths


def test_log_event_appends(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    log_event(p, "ingest", "kb-001", "ingested foo.pdf")
    log_event(p, "ingest", "kb-002", "ingested bar.pdf")

    log = p.llm_wiki_log.read_text(encoding="utf-8")
    assert "ingested foo.pdf" in log
    assert "ingested bar.pdf" in log
    assert "kb-001" in log


def test_log_event_creates_header_on_first(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    log_event(p, "ingest", "kb-001", "first")
    log = p.llm_wiki_log.read_text(encoding="utf-8")
    assert "# Wiki Operation Log" in log


def test_read_log_returns_events(tmp_path):
    ensure_knowledge_base(tmp_path)
    p = WikiPaths(tmp_path)
    log_event(p, "ingest", "kb-1", "first")
    log_event(p, "ingest", "kb-2", "second")

    events = read_log(p)
    assert len(events) == 2
    assert events[0]["event"] == "ingest"
    assert events[0]["task_id"] == "kb-1"
    assert events[1]["task_id"] == "kb-2"
