"""Tests for Task 2.2 — folder_context propagation, batch tracking, .html collector."""
import json



# ---------------------------------------------------------------------------
# folder_context propagation
# ---------------------------------------------------------------------------

class TestFolderContextPropagation:
    def test_knowledge_task_stores_folder_context(self):
        """KnowledgeTask accepts and stores folder_context."""
        from src.types import KnowledgeTask, SourceType, TaskStatus
        task = KnowledgeTask(
            id="t1", source="raw/sources/test.md", source_type=SourceType.FILE,
            status=TaskStatus.PENDING, task_hash="abc",
            created_at=0, updated_at=0,
            folder_context="Chapter 3 of the novel",
        )
        assert task.folder_context == "Chapter 3 of the novel"

    def test_knowledge_task_stores_batch_id(self):
        """KnowledgeTask accepts and stores batch_id."""
        from src.types import KnowledgeTask, SourceType, TaskStatus
        task = KnowledgeTask(
            id="t1", source="raw/sources/test.md", source_type=SourceType.FILE,
            status=TaskStatus.PENDING, task_hash="abc",
            created_at=0, updated_at=0,
            batch_id="kb-batch-abc123def456",
        )
        assert task.batch_id == "kb-batch-abc123def456"

    def test_knowledge_task_defaults_none(self):
        """KnowledgeTask folder_context and batch_id default to None."""
        from src.types import KnowledgeTask, SourceType, TaskStatus
        task = KnowledgeTask(
            id="t1", source="raw/sources/test.md", source_type=SourceType.FILE,
            status=TaskStatus.PENDING, task_hash="abc",
            created_at=0, updated_at=0,
        )
        assert task.folder_context is None
        assert task.batch_id is None

    def test_enqueue_stores_folder_context_on_task(self):
        """QueueService.enqueue() stores folder_context on the KnowledgeTask."""
        from src.queue.service import QueueService
        from src.queue.ports import QueueBackend, EventEmitter, RetryPolicy
        from src.queue.in_flight import InMemoryInFlightTracker
        from src.types import SourceType
        from src.circuit_breaker import get_circuit_breaker, CircuitState

        # Reset breaker to clean state
        _cb = get_circuit_breaker("task_queue")
        _cb.state = CircuitState.CLOSED
        _cb.failure_count = 0

        class MemBackend(QueueBackend):
            def __init__(self):
                self.tasks: dict = {}
            def enqueue(self, task):
                self.tasks[task.id] = task
            def enqueue_batch(self, tasks):
                for t in tasks:
                    self.tasks[t.id] = t
            def find(self, tid):
                return self.tasks.get(tid)
            def find_by_hash(self, h):
                return [t for t in self.tasks.values() if t.task_hash == h]
            def save(self, task):
                self.tasks[task.id] = task
            def remove(self, tid):
                self.tasks.pop(tid, None)
            def iter_ids(self):
                return list(self.tasks.keys())
            def snapshot(self, *, in_flight_ids=None):
                return [t for t in self.tasks.values()]

        class NoopEmitter(EventEmitter):
            def emit(self, name, payload=None): pass

        class NoopRetry(RetryPolicy):
            def decide(self, task, status, error, breaker):
                from collections import namedtuple
                D = namedtuple("Decision", "new_status should_record_breaker_failure")
                return D(new_status=status, should_record_breaker_failure=False)

        backend = MemBackend()
        svc = QueueService(
            backend=backend, tracker=InMemoryInFlightTracker(),
            emitter=NoopEmitter(), retry_policy=NoopRetry(),
        )
        tid = svc.enqueue(
            "raw/sources/ch3.md", SourceType.FILE, "hash-001",
            folder_context="Chapter 3",
        )
        task = backend.find(tid)
        assert task is not None
        assert task.folder_context == "Chapter 3"

    def test_enqueue_batch_stores_folder_context(self):
        """enqueue_batch() stores folder_context and batch_id on KnowledgeTask."""
        from src.queue.service import QueueService
        from src.queue.ports import QueueBackend, EventEmitter, RetryPolicy
        from src.queue.in_flight import InMemoryInFlightTracker
        from src.types import SourceType

        class MemBackend(QueueBackend):
            def __init__(self):
                self.tasks: dict = {}
            def enqueue(self, task):
                self.tasks[task.id] = task
            def enqueue_batch(self, tasks):
                for t in tasks:
                    self.tasks[t.id] = t
            def find(self, tid):
                return self.tasks.get(tid)
            def find_by_hash(self, h):
                return [t for t in self.tasks.values() if t.task_hash == h]
            def save(self, task):
                self.tasks[task.id] = task
            def remove(self, tid):
                self.tasks.pop(tid, None)
            def iter_ids(self):
                return list(self.tasks.keys())
            def snapshot(self, *, in_flight_ids=None):
                return [t for t in self.tasks.values()]

        class NoopEmitter(EventEmitter):
            def emit(self, name, payload=None): pass

        class NoopRetry(RetryPolicy):
            def decide(self, task, status, error, breaker):
                from collections import namedtuple
                D = namedtuple("Decision", "new_status should_record_breaker_failure")
                return D(new_status=status, should_record_breaker_failure=False)

        backend = MemBackend()
        svc = QueueService(
            backend=backend, tracker=InMemoryInFlightTracker(),
            emitter=NoopEmitter(), retry_policy=NoopRetry(),
        )
        task_ids = svc.enqueue_batch(
            [{"source": "raw/sources/ch3.md", "source_type": SourceType.FILE, "task_hash": "hash-003"}],
            folder_context="Chapter 3",
            batch_id="kb-batch-test123",
        )
        assert len(task_ids) == 1
        task = backend.find(task_ids[0])
        assert task is not None
        assert task.folder_context == "Chapter 3"
        assert task.batch_id == "kb-batch-test123"


# ---------------------------------------------------------------------------
# Batch tracking
# ---------------------------------------------------------------------------

class TestBatchTracking:
    def test_folder_enqueue_creates_batch_id(self, tmp_path, monkeypatch):
        """enqueue_source with folder creates a batch_id and writes batch state."""
        import src.services.ingest as _mod

        project_dir = tmp_path / "kb"
        project_dir.mkdir()
        docs_dir = project_dir / "data" / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "test.md").write_text("# Test", encoding="utf-8")

        # Anchor CWD inside the project tree so os.path.abspath of
        # "data/docs" lands under project_root (Windows hosts put
        # pytest's tmp_path on a different drive than CWD, which
        # triggers a cross-drive ValueError in os.path.relpath).
        monkeypatch.chdir(project_dir)

        # Stub resolve_project
        from src.project.context import ProjectContext
        from src.wiki.core.paths import WikiPaths
        identity = type("I", (), {"id": "u"})()
        ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
        paths = WikiPaths(project_dir)

        orig_resolve = _mod.resolve_project
        _mod.resolve_project = lambda pid, by_id_only=True: (ctx, paths)

        captured_batch = {}
        def fake_enqueue_batch(items, project_id=None, **kw):
            captured_batch["items"] = items
            captured_batch["kw"] = kw
            return ["task-789"]
        orig_enqueue_batch = _mod.enqueue_batch
        _mod.enqueue_batch = fake_enqueue_batch

        # Stub advance
        orig_qs = _mod.get_default_queue_service
        _mod.get_default_queue_service = lambda: type("S", (), {"advance": lambda self, **kw: None})()

        try:
            result = _mod.enqueue_source("u", {"folder": "data/docs"})
        finally:
            _mod.resolve_project = orig_resolve
            _mod.enqueue_batch = orig_enqueue_batch
            _mod.get_default_queue_service = orig_qs

        assert result["status"] == "batch_queued"
        assert "batchId" in result
        assert result["batchId"].startswith("kb-batch-")
        # batch_id passed to enqueue_batch
        assert captured_batch["kw"].get("batch_id") == result["batchId"]

    def test_batch_state_file_written(self, tmp_path, monkeypatch):
        """Folder enqueue writes batch_build_state.json."""
        import src.services.ingest as _mod

        project_dir = tmp_path / "kb"
        project_dir.mkdir()
        docs_dir = project_dir / "data" / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "a.md").write_text("# A", encoding="utf-8")

        # Anchor CWD into the project tree (Windows cross-drive guard).
        monkeypatch.chdir(project_dir)

        from src.project.context import ProjectContext
        from src.wiki.core.paths import WikiPaths
        identity = type("I", (), {"id": "u"})()
        ctx = ProjectContext(identity=identity, path=project_dir, name="p", schema_version="v2.0")
        paths = WikiPaths(project_dir)

        orig_resolve = _mod.resolve_project
        _mod.resolve_project = lambda pid, by_id_only=True: (ctx, paths)

        def fake_enqueue_batch(items, project_id=None, **kw):
            return ["task-789"]
        orig_enqueue_batch = _mod.enqueue_batch
        _mod.enqueue_batch = fake_enqueue_batch
        orig_qs = _mod.get_default_queue_service
        _mod.get_default_queue_service = lambda: type("S", (), {"advance": lambda self, **kw: None})()

        try:
            result = _mod.enqueue_source("u", {"folder": "data/docs"})
        finally:
            _mod.resolve_project = orig_resolve
            _mod.enqueue_batch = orig_enqueue_batch
            _mod.get_default_queue_service = orig_qs

        batch_id = result["batchId"]
        state_file = project_dir / ".index" / "batch_build_state.json"
        assert state_file.exists()
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert batch_id in state
        assert state[batch_id]["folder"] == "data/docs"
        assert state[batch_id]["status"] == "in_progress"
        assert state[batch_id]["enqueued"] == 1


# ---------------------------------------------------------------------------
# .html collector support
# ---------------------------------------------------------------------------

class TestHtmlCollector:
    def test_html_collected_via_decode_and_strip(self, tmp_path):
        """HTML files: _decode_text_file + html_to_text strips tags."""
        from src.pipeline.collector import _decode_text_file
        from src.utils.text import html_to_text

        html_bytes = "<html><body><h1>Test</h1><p>Hello world.</p></body></html>".encode("utf-8")
        html_str = _decode_text_file(html_bytes, "test.html")
        content = html_to_text(html_str)
        assert "Test" in content
        assert "Hello world" in content
        assert "<h1>" not in content
        assert "<body>" not in content

    def test_html_entity_decoding(self):
        """HTML entities are decoded by html_to_text."""
        from src.utils.text import html_to_text

        content = html_to_text("<p>Price: 5 &lt; 10 &amp; 3 &gt; 1</p>")
        assert "5 < 10" in content
        assert "3 > 1" in content

    def test_html_with_script_tags_stripped(self):
        """Script tag contents are stripped by html_to_text."""
        from src.utils.text import html_to_text

        html = (
            "<html><head><script>console.log('noise');</script></head>"
            "<body><p>Visible text</p></body></html>"
        )
        content = html_to_text(html)
        assert "Visible text" in content
        assert "console.log" not in content


# ---------------------------------------------------------------------------
# Single file — no regression
# ---------------------------------------------------------------------------

class TestSingleFileNoRegression:
    def test_single_file_enqueue_no_folder_context(self):
        """Single file enqueue without folder_context works as before."""
        from src.types import KnowledgeTask, SourceType, TaskStatus
        task = KnowledgeTask(
            id="t1", source="raw/sources/test.md", source_type=SourceType.FILE,
            status=TaskStatus.PENDING, task_hash="abc",
            created_at=0, updated_at=0,
        )
        assert task.folder_context is None
        assert task.batch_id is None
