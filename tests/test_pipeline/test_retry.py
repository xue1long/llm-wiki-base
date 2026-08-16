"""plan 1.9 — LLM 调用接线：retry_with_backoff 接线 + 422 永久隔离 + llm 熔断直跑接线.

C1 P0（spec §11.7.2）：429 读 Retry-After / 422 PermanentFailure 分类 / transient
退避；provider 层统一封装覆盖 generator/analyzer(budgeted)/c_grade/QualityJudge
全部 4 处调用点；直跑路径（phase4_batch._ingest_one）record_failure/success；
executor 顶层按 breaker OPEN 暂停整批等待恢复。
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from src.circuit_breaker import CircuitState, get_circuit_breaker
from src.pipeline import retry as retry_mod
from src.pipeline.retry import (
    CircuitBreakerOpen,
    PermanentFailure,
    RetryExhausted,
    classify_error,
    retry_with_backoff,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_llm_breaker():
    """Each test starts with a fresh global 'llm' breaker (CLOSED)."""
    import src.circuit_breaker as cb
    cb._circuit_breakers.pop("llm", None)
    yield
    cb._circuit_breakers.pop("llm", None)


@pytest.fixture
def sleep_log(monkeypatch):
    """Record every asyncio.sleep call in retry.py and skip real waiting."""
    log: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        log.append(seconds)

    monkeypatch.setattr(retry_mod, "_sleep", _fake_sleep)
    return log


def _http_status_error(status: int, *, retry_after: str | None = None,
                       text: str = "") -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.test/v1/chat/completions")
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    resp = httpx.Response(status, request=req, headers=headers, text=text)
    return httpx.HTTPStatusError(f"HTTP {status}", request=req, response=resp)


# ---------------------------------------------------------------------------
# classify_error — 429 / 422 / 5xx / 断连 / RuntimeError 包装
# ---------------------------------------------------------------------------

def test_classify_429_rate_limit():
    assert classify_error(_http_status_error(429)) == "rate_limit"


def test_classify_422_content_moderation():
    assert classify_error(_http_status_error(422)) == "content_moderation"


def test_classify_5xx_transient():
    for status in (500, 502, 503):
        assert classify_error(_http_status_error(status)) == "transient"


def test_classify_disconnect_transient():
    assert classify_error(httpx.ConnectError("refused")) == "transient"
    assert classify_error(httpx.ReadTimeout("slow")) == "transient"


def test_classify_unwraps_runtime_error_chain():
    """Provider 把底层 httpx 错误包成 RuntimeError（OpenAI/Ollama 模式）时
    classify 必须沿 __cause__ 链找到真实状态码。"""
    inner = _http_status_error(429, retry_after="5")
    wrapped = RuntimeError("OpenAI complete failed: HTTP 429")
    wrapped.__cause__ = inner
    assert classify_error(wrapped) == "rate_limit"

    inner_422 = _http_status_error(422)
    wrapped_422 = RuntimeError("OpenAI complete failed: HTTP 422")
    wrapped_422.__cause__ = inner_422
    assert classify_error(wrapped_422) == "content_moderation"


def test_classify_other_status_permanent():
    assert classify_error(_http_status_error(400)) == "permanent"


# ---------------------------------------------------------------------------
# retry_with_backoff — 各路径
# ---------------------------------------------------------------------------

async def test_retry_success_first_try_no_sleep(sleep_log):
    calls = []

    async def fn():
        calls.append(1)
        return "ok"

    assert await retry_with_backoff(fn, retry_delays=(0.001,)) == "ok"
    assert len(calls) == 1
    assert sleep_log == []


async def test_retry_429_waits_retry_after(sleep_log):
    """429 → 读 Retry-After 头并等待该时长（cap 内），然后重试成功。"""
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) == 1:
            raise _http_status_error(429, retry_after="2")
        return "ok"

    result = await retry_with_backoff(fn, retry_delays=(0.001,), max_retry_after=60)
    assert result == "ok"
    assert len(calls) == 2
    # 429 分支等待的是 Retry-After 值，而不是退避表
    assert sleep_log == [2.0]


async def test_retry_429_retry_after_capped(sleep_log):
    """Retry-After 超过 cap 时截断到 max_retry_after。"""
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) == 1:
            raise _http_status_error(429, retry_after="300")
        return "ok"

    await retry_with_backoff(fn, retry_delays=(0.001,), max_retry_after=10)
    assert len(calls) == 2
    assert sleep_log == [10.0]


async def test_retry_429_missing_retry_after_defaults_to_5s(sleep_log):
    """M-7: Retry-After 头缺失 → 429 等待默认 5s（_parse_retry_after 兜底）。"""
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) == 1:
            raise _http_status_error(429)  # 无 Retry-After 头
        return "ok"

    result = await retry_with_backoff(fn, retry_delays=(0.001,), max_retry_after=60)
    assert result == "ok"
    assert len(calls) == 2
    assert sleep_log == [5.0]


async def test_retry_422_permanent_failure_no_retry(sleep_log):
    """422 → PermanentFailure 立即抛出，不重试。"""
    calls = []

    async def fn():
        calls.append(1)
        raise _http_status_error(422)

    with pytest.raises(PermanentFailure):
        await retry_with_backoff(fn)
    assert len(calls) == 1
    assert sleep_log == []


async def test_retry_5xx_transient_backoff_then_success(sleep_log):
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) < 3:
            raise _http_status_error(503)
        return "ok"

    result = await retry_with_backoff(fn, retry_delays=(0.1, 0.2, 0.4))
    assert result == "ok"
    assert len(calls) == 3
    # 前两次失败使用退避表 0.1 / 0.2
    assert sleep_log == [0.1, 0.2]


async def test_retry_disconnect_transient_then_success(sleep_log):
    calls = []

    async def fn():
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("connection refused")
        return "ok"

    assert await retry_with_backoff(fn, retry_delays=(0.1,)) == "ok"
    assert len(calls) == 2


async def test_retry_all_transient_exhausted_raises(sleep_log):
    calls = []

    async def fn():
        calls.append(1)
        raise _http_status_error(500)

    with pytest.raises(RetryExhausted):
        await retry_with_backoff(fn, max_retries=2, retry_delays=(0.1, 0.2))
    assert len(calls) == 3  # 初始 + 2 次重试


async def test_retry_breaker_open_raises_immediately(sleep_log):
    """breaker OPEN → CircuitBreakerOpen 立即抛出，fn 不被调用（熔断暂停）。"""
    breaker = get_circuit_breaker("llm")
    breaker.state = CircuitState.OPEN

    calls = []

    async def fn():
        calls.append(1)
        return "ok"

    with pytest.raises(CircuitBreakerOpen):
        await retry_with_backoff(fn)
    assert calls == []
    assert sleep_log == []


# ---------------------------------------------------------------------------
# Provider 层统一封装 — RetryLLMProvider
# ---------------------------------------------------------------------------

class _FakeProvider:
    """最小 LLMProvider 双胞胎：complete 计数、可触发 429 / 422 / 5xx。"""

    def __init__(self):
        self.calls: list[dict] = []
        self.model = "fake-model"
        self.config = {"name": "fake"}
        self._response_format_ok: bool | None = True
        self.closed = False

    async def complete(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return {"content": "ok"}

    async def chat(self, messages, **kwargs):
        return await self.complete(messages, **kwargs)

    async def embed(self, text):
        return ["v"]

    async def health_check(self):
        return {"ok": True}

    async def check_response_format(self):
        return {"ok": True}

    async def close(self):
        self.closed = True


def test_retry_llm_provider_wraps_complete(sleep_log):
    """provider 层包装：complete() 经 retry_with_backoff，429 一次后成功。"""
    from src.pipeline.retry import RetryLLMProvider

    inner = _FakeProvider()

    async def _flaky(messages, **kwargs):
        inner.calls.append({"messages": messages, "kwargs": kwargs})
        if len(inner.calls) == 1:
            raise _http_status_error(429, retry_after="1")
        return {"content": "ok"}

    inner.complete = _flaky
    wrapped = RetryLLMProvider(inner, retry_delays=(0.1,))
    resp = asyncio.run(wrapped.complete([{"role": "user", "content": "hi"}]))
    assert resp == {"content": "ok"}
    assert len(inner.calls) == 2
    assert sleep_log == [1.0]


def test_retry_llm_provider_422_permanent(sleep_log):
    from src.pipeline.retry import RetryLLMProvider

    inner = _FakeProvider()

    async def _flaky(messages, **kwargs):
        inner.calls.append({"messages": messages, "kwargs": kwargs})
        raise _http_status_error(422)

    inner.complete = _flaky
    wrapped = RetryLLMProvider(inner)
    with pytest.raises(PermanentFailure):
        asyncio.run(wrapped.complete([{"role": "user", "content": "hi"}]))
    assert len(inner.calls) == 1


def test_retry_llm_provider_delegates_other_members():
    """包装器必须透传非 complete 成员（model/config/health_check/close/embed）。"""
    from src.pipeline.retry import RetryLLMProvider

    inner = _FakeProvider()
    wrapped = RetryLLMProvider(inner)

    assert wrapped.model == "fake-model"
    assert wrapped.config == {"name": "fake"}
    assert wrapped._response_format_ok is True
    assert asyncio.run(wrapped.health_check()) == {"ok": True}
    assert asyncio.run(wrapped.check_response_format()) == {"ok": True}
    assert asyncio.run(wrapped.embed("t")) == ["v"]
    asyncio.run(wrapped.close())
    assert inner.closed is True


def test_retry_llm_provider_breaker_open_short_circuits(sleep_log):
    """breaker OPEN 时包装器的 complete 立即抛 CircuitBreakerOpen，不调用内层。"""
    from src.pipeline.retry import RetryLLMProvider

    breaker = get_circuit_breaker("llm")
    breaker.state = CircuitState.OPEN

    inner = _FakeProvider()
    wrapped = RetryLLMProvider(inner)

    with pytest.raises(CircuitBreakerOpen):
        asyncio.run(wrapped.complete([{"role": "user", "content": "hi"}]))
    assert inner.calls == []


def test_retry_llm_provider_chat_goes_through_retry(sleep_log):
    """M-7: wrapper.chat() 必须经 retry_with_backoff（委托 wrapper.complete，
    而不是直接透传 inner.chat 绕过重试）。"""
    from src.pipeline.retry import RetryLLMProvider

    inner = _FakeProvider()

    async def _flaky(messages, **kwargs):
        inner.calls.append({"messages": messages, "kwargs": kwargs})
        if len(inner.calls) == 1:
            raise _http_status_error(429, retry_after="1")
        return {"content": "ok"}

    inner.complete = _flaky
    wrapped = RetryLLMProvider(inner, retry_delays=(0.1,))
    resp = asyncio.run(wrapped.chat([{"role": "user", "content": "hi"}]))
    assert resp == {"content": "ok"}
    assert len(inner.calls) == 2
    assert sleep_log == [1.0]


# ---------------------------------------------------------------------------
# create_llm_provider 覆盖 — 接线点清单（grep 断言，防漏接 budgeted/judge）
# ---------------------------------------------------------------------------

def test_factory_returns_retry_wrapped_provider(monkeypatch):
    """create_llm_provider 返回 RetryLLMProvider —— 所有工厂产出的 provider
    都自动带重试（覆盖 generator/c_grade/analyzer-budgeted/QualityJudge）。"""
    from src.llm import registry as reg
    from src.llm.openai_provider import OpenAIProvider
    from src.llm.types import ProviderConfig
    from src.pipeline.retry import RetryLLMProvider

    cfg = ProviderConfig(
        name="fake", type="openai", api_key="k",
        base_url="http://fake", default_chat_model="m",
    )
    # create_llm_provider 在函数体内 `from .registry import ProviderRegistry`，
    # 所以必须 patch 模块级符号而不是 factory 上的引用。
    monkeypatch.setattr(reg.ProviderRegistry, "get", staticmethod(lambda *a, **k: cfg))

    from src.llm import provider_factory as pf
    provider = pf.create_llm_provider("fake")
    assert isinstance(provider, RetryLLMProvider)
    # 内层仍是真实 OpenAIProvider（装饰而非替换）
    assert isinstance(provider._inner, OpenAIProvider)


def test_wiring_coverage_llm_call_sites():
    """plan 1.9 review E — 4 处 LLM 调用点的 provider 全部来自工厂封装链。

    用 grep 断言（防漏接 budgeted/judge）：每个调用点要么直接
    ``create_llm_provider(...)``（QualityJudge），要么经 pipeline
    ``_get_provider()`` 取 provider（generator / c_grade_handler /
    analyzer→budgeted）。
    """
    src_root = Path(__file__).resolve().parents[2] / "src"

    # QualityJudge 自己经工厂建 provider
    judge_src = (src_root / "quality" / "judge.py").read_text(encoding="utf-8")
    assert "create_llm_provider(" in judge_src
    assert ".complete(" in judge_src

    # generator / c_grade_handler / analyzer 的 provider 由 pipeline 传入
    gen_src = (src_root / "pipeline" / "generator.py").read_text(encoding="utf-8")
    assert "provider.complete(" in gen_src

    cg_src = (src_root / "pipeline" / "c_grade_handler.py").read_text(encoding="utf-8")
    assert "provider.complete(" in cg_src

    budgeted_src = (src_root / "lib" / "budgeted.py").read_text(encoding="utf-8")
    assert "self.provider.complete(" in budgeted_src

    # pipeline._get_provider → create_llm_provider（工厂封装链的入口）
    pipeline_src = (src_root / "pipeline" / "__init__.py").read_text(encoding="utf-8")
    assert "create_llm_provider(" in pipeline_src

    # 工厂本身确实返回 RetryLLMProvider
    factory_src = (src_root / "llm" / "provider_factory.py").read_text(encoding="utf-8")
    assert "RetryLLMProvider" in factory_src

    # 不允许任何调用点绕过工厂直接 new 具体 provider
    for rel in ("pipeline/generator.py", "pipeline/c_grade_handler.py",
                "lib/budgeted.py", "quality/judge.py"):
        text = (src_root / rel).read_text(encoding="utf-8")
        assert "OllamaProvider(" not in text
        assert "OpenAIProvider(" not in text
        assert "AnthropicProvider(" not in text


# ---------------------------------------------------------------------------
# 直跑路径接线 — phase4_batch._generate_batch / _ingest_one
# ---------------------------------------------------------------------------

def _make_batch_root(tmp_path):
    root = tmp_path / "kb"
    raw = root / "raw" / "sources"
    raw.mkdir(parents=True)
    (raw / "a.md").write_text("内容 A", encoding="utf-8")
    return root, ["raw/sources/a.md"]


@pytest.fixture
def patch_generate(monkeypatch):
    """把 phase4_batch 内部（经 src.pipeline.ingest 局部导入）的
    generate_ingest 换成可控假实现。"""
    import scripts.phase4_batch as p4
    from src.pipeline import ingest as ingest_mod

    fake = {"fn": None}

    async def _gen(**kwargs):
        assert fake["fn"] is not None
        return await fake["fn"](**kwargs)

    monkeypatch.setattr(ingest_mod, "generate_ingest", _gen)
    # 熔断等待 / 重试退避不真等
    async def _no_sleep(_s):
        pass
    monkeypatch.setattr(p4.asyncio, "sleep", _no_sleep)
    return fake


def _run_batch(p4, root, files, *, breaker=None):
    paths = SimpleNamespace(root=str(root))
    return asyncio.run(p4._generate_batch(
        paths=paths, provider=object(), files=files,
        completed_files=set(), skip_files=set(),
        concurrency=1, batch_no=0, root=root,
    ))


def test_ingest_one_success_records_breaker_success(tmp_path, patch_generate):
    """_ingest_one 成功 → llm breaker record_success（CLOSED 下清零失败计数）。"""
    import scripts.phase4_batch as p4

    root, files = _make_batch_root(tmp_path)

    async def _ok(**kwargs):
        return [], [], {"rejected": None}

    patch_generate["fn"] = _ok
    gen = _run_batch(p4, root, files)

    breaker = get_circuit_breaker("llm")
    assert gen["ok"] == 1
    assert breaker.failure_count == 0


def test_ingest_one_failure_records_breaker_failure(tmp_path, patch_generate):
    """_ingest_one 传输失败 → llm breaker record_failure。"""
    import scripts.phase4_batch as p4

    root, files = _make_batch_root(tmp_path)

    async def _fail(**kwargs):
        raise _http_status_error(503)

    patch_generate["fn"] = _fail
    gen = _run_batch(p4, root, files)

    breaker = get_circuit_breaker("llm")
    assert breaker.failure_count >= 1
    assert gen["file_results"]["raw/sources/a.md"]["ok"] is False


def test_ingest_one_422_marks_permanent_failed_no_breaker_record(
        tmp_path, patch_generate):
    """422 → permanent_failed 标记、不进重试、不记 breaker failure。"""
    import scripts.phase4_batch as p4

    root, files = _make_batch_root(tmp_path)

    async def _moderation(**kwargs):
        # 与 wrapped provider 的实际行为一致：422 由 retry_with_backoff
        # 分类为 PermanentFailure 抛给直跑路径。
        raise PermanentFailure("HTTP 422 content moderation — source cannot be processed by LLM")

    patch_generate["fn"] = _moderation
    gen = _run_batch(p4, root, files)

    res = gen["file_results"]["raw/sources/a.md"]
    assert res["permanent_failed"] is True
    assert res["ok"] is False
    assert gen["err"] == 0  # permanent_failed 不计入 err
    breaker = get_circuit_breaker("llm")
    assert breaker.failure_count == 0


def test_executor_pauses_when_breaker_open(monkeypatch, tmp_path, patch_generate):
    """breaker OPEN → 直跑路径暂停整批：generate_ingest 不被调用，
    恢复后才继续。"""
    import scripts.phase4_batch as p4

    root, files = _make_batch_root(tmp_path)
    breaker = get_circuit_breaker("llm")
    breaker.state = CircuitState.OPEN

    called = []

    async def _gen(**kwargs):
        called.append(1)
        return [], [], {}

    patch_generate["fn"] = _gen

    # 用一个"先 OPEN、后放行"的假 breaker 驱动 _await_breaker_recovery，
    # 避免真等 60s 冷却。
    from src.circuit_breaker import CircuitBreaker
    import scripts.phase4_batch as p4_mod

    class _ControlledBreaker(CircuitBreaker):
        def __init__(self):
            super().__init__(name="llm")
            self.state = CircuitState.OPEN
            self._calls = 0

        def can_execute(self):
            self._calls += 1
            if self._calls >= 2:  # 第一次暂停，第二次放行（HALF_OPEN）
                self.state = CircuitState.HALF_OPEN
                return True
            return False

    controlled = _ControlledBreaker()
    original_recovery = p4_mod._await_breaker_recovery
    monkeypatch.setattr(p4_mod, "_await_breaker_recovery",
                        lambda *a, **k: original_recovery(controlled, *a, **k))

    gen = asyncio.run(p4_mod._generate_batch(
        paths=SimpleNamespace(root=str(root)), provider=object(),
        files=files, completed_files=set(), skip_files=set(),
        concurrency=1, batch_no=0, root=root,
    ))
    # 熔断恢复后继续执行该文件
    assert called == [1]
    assert gen["ok"] == 1


def test_retry_with_backoff_has_callers():
    """retry_with_backoff 不再是死代码：RetryLLMProvider.complete 引用它。"""
    from src.pipeline import retry as retry_mod
    from src.pipeline.retry import RetryLLMProvider

    assert callable(retry_mod.retry_with_backoff)
    # RetryLLMProvider.complete 委托 retry_with_backoff
    src = Path(retry_mod.__file__).read_text(encoding="utf-8")
    assert "retry_with_backoff(" in src
    assert "class RetryLLMProvider" in src


# ---------------------------------------------------------------------------
# I-1：422 穿透 ingest.py fallback 级联（reviewer Important-1）
# ---------------------------------------------------------------------------

async def test_generate_ingest_422_permanent_failure_bubbles(tmp_path):
    """I-1: 422 content moderation 必须经 generate_ingest 冒泡为 PermanentFailure，
    不得被 chunked→unified→two-step fallback 级联吞掉（B2 空耗 LLM 消除）。

    生产链：factory 用 RetryLLMProvider 包 provider → complete() 把 422 分类为
    PermanentFailure → generate_ingest 的 fallback 级联必须放行而非重发。
    """
    from src.pipeline.ingest import generate_ingest
    from src.pipeline.retry import PermanentFailure, RetryLLMProvider
    from src.wiki.core.paths import WikiPaths
    from src.wiki.storage.ensure import ensure_knowledge_base

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "moderation.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容审核拒绝的内容", encoding="utf-8")

    calls = {"n": 0}

    class _ModerationProvider:
        async def complete(self, messages, **kwargs):
            calls["n"] += 1
            raise _http_status_error(422)
        async def chat(self, messages, **kwargs):
            return await self.complete(messages, **kwargs)

    provider = RetryLLMProvider(_ModerationProvider(), retry_delays=(0.001,))

    with pytest.raises(PermanentFailure):
        await generate_ingest(
            paths=paths,
            source_path=raw,
            source_text="内容审核拒绝的内容",
            provider=provider,
            task_id="kb-moderation",
        )
    # 422 首次 LLM 调用即冒泡：fallback 级联不得重发（unified 一次即停）
    assert calls["n"] == 1, (
        "422 应首次 LLM 调用后立即冒泡，fallback 级联不得重发调用"
    )


# ---------------------------------------------------------------------------
# Phase 3 实测接线：_commit_all 透传 missing_slugs → knowledge_gaps
# ---------------------------------------------------------------------------


def test_commit_all_passes_missing_slugs_to_commit_ingest(tmp_path, monkeypatch):
    """1.3 O6 接线：phase4_batch 的 commit 必须把 raw 的未解析引用透传给
    commit_ingest（→ knowledge_gaps.json）。

    Phase 3 首批实测暴露：_commit_all 此前只传 paths/pages/task_id，
    generate meta 的 missing_slugs 被丢弃 → gap 账本在 batch 路径从未写入，
    批内断链无法按 F2 语义归入 gap。本测试锁定透传。
    """
    import scripts.phase4_batch as p4
    from src.wiki.core.paths import WikiPaths
    from src.wiki.core.types import PageType, WikiPage
    from src.wiki.storage.ensure import ensure_knowledge_base

    captured = {}

    async def _fake_commit(*args, **kwargs):
        captured.update(kwargs)
        return None

    # _commit_all 内部局部导入 commit_ingest —— monkeypatch src.pipeline.ingest
    from src.pipeline import ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "commit_ingest", _fake_commit)

    ensure_knowledge_base(tmp_path)
    paths = WikiPaths(tmp_path)
    raw = paths.raw_sources / "gap-raw.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("内容", encoding="utf-8")

    now = int(__import__("time").time() * 1000)
    page = WikiPage(
        id="src-gap", title="gap", type=PageType.SOURCE,
        sources=["raw/sources/gap-raw.md"], body="## 摘要\n\n摘要",
        grade="A", created_at=now, updated_at=now,
    )
    file_results = {
        "raw/sources/gap-raw.md": {
            "ok": True,
            "meta": {"missing_slugs": [{"slug": "幽灵概念", "referenced_by": ["src-gap"]}]},
        },
    }

    entry, rc = asyncio.run(p4._commit_all(
        paths=paths, pages=[page], extras=[], batch_key="batch_0",
        batch_files=["raw/sources/gap-raw.md"], root=tmp_path,
        task_id="b0", file_results=file_results,
    ))
    # POSTCHECK 依赖真实写盘（此处 commit_ingest 被 mock），rc 可能非 0；
    # 本测试只锁 missing_slugs 透传，不依赖 POSTCHECK 结果。
    assert captured.get("missing_slugs") == [
        {"slug": "幽灵概念", "referenced_by": ["src-gap"]}
    ], f"missing_slugs must reach commit_ingest, got: {captured.get('missing_slugs')}"
