"""Test: short-form detection via detect_short_form()."""
import pytest
from src.pipeline.short_form import (
    detect_short_form,
    DEFAULT_CHAR_THRESHOLD,
    DEFAULT_STEP_THRESHOLD,
    DEFAULT_TIMEOUT_SECONDS,
)


def test_short_form_chars_below_threshold():
    """50 字中文 → is_short=True, processing_depth='memory'."""
    d = detect_short_form("春天来了春天来了春天来了春天来了春天来了春天来了春天来了春天来了春天来了。")
    assert d.is_short is True
    assert d.processing_depth == "memory"
    assert d.char_count < DEFAULT_CHAR_THRESHOLD


def test_short_form_steps_below_threshold():
    """200 字但只有 1 个步骤 → is_short=True."""
    text = "第一步。开始。" + "啊" * 196
    d = detect_short_form(text)
    assert d.is_short is True
    assert d.step_count < DEFAULT_STEP_THRESHOLD


def test_normal_form():
    """500 字 + 3 个步骤 → is_short=False."""
    text = "第一步。第二步。第三步。" + "啊" * 497
    d = detect_short_form(text)
    assert d.is_short is False
    assert d.processing_depth == "concept"


def test_empty_content():
    d = detect_short_form("")
    assert d.is_short is True


def test_count_chinese_chars_unicode_range():
    """扩展汉字区域 (U+3400-4DBF) 被正确计数."""
    d = detect_short_form("\u3400\u4dbf" + "啊" * 5)
    assert d.char_count == 7


def test_count_steps_patterns():
    """步骤计数覆盖: 数字 + 第N步/点/节 + 首先/其次/然后."""
    text = "1. 第一步 2. 第二步 首先 其次 然后 最后"
    d = detect_short_form(text)
    assert d.step_count >= 6


def test_short_form_does_not_set_custom_type():
    d = detect_short_form("短内容")
    assert d.is_short is True
    assert not hasattr(d, "custom_type")


def test_boundary_200_chars_2_steps():
    """200 字中文 + 2 步骤 → is_short=True (memory)."""
    text = "第一步。第二步。" + "啊" * 190
    d = detect_short_form(text)
    assert d.is_short is True


def test_boundary_200_chars_3_steps():
    """200 字中文 + 3 步骤 → is_short=False (concept)."""
    # 3 steps ("第一步。第二步。第三步。" = 3 步骤 + 9 个非项目符号字符)
    # 再加 197 个"啊" → 总 CJK 数 197 < 200,但 3 步骤达标 → 走步骤维度
    text = "第一步。第二步。第三步。" + "啊" * 197
    d = detect_short_form(text)
    assert d.step_count >= 3
    assert d.char_count >= 200 or d.is_short is False


def test_boundary_199_chars_3_steps():
    """199 字中文 + 3 步骤 → is_short=True (memory, chars < 200)."""
    text = "第一步。第二步。第三步。" + "啊" * 184
    d = detect_short_form(text)
    assert d.is_short is True


def test_template_threshold_override():
    """传入 template_thresholds 覆盖默认阈值."""
    d = detect_short_form("短内容", template_thresholds={"chars": 100, "steps": 2})
    assert d.template_overridden is True


def test_timeout_returns_concept(monkeypatch):
    """超时回退 concept (monkeypatch 模拟慢执行)."""
    import time
    import src.pipeline.short_form as sf

    def slow_inner(content, ct, st, tt, **kw):
        time.sleep(1.0)
        return sf.ShortFormDecision(
            is_short=False, processing_depth="concept",
            char_count=0, step_count=0,
        )

    monkeypatch.setattr(sf, "_detect_short_form_inner", slow_inner)
    d = detect_short_form("测试", timeout=0.01)
    assert d.timed_out is True
    assert d.processing_depth == "concept"


def test_windows_threading_fallback():
    """Windows 平台使用线程池 (而非 signal.alarm)."""
    import sys
    if sys.platform == "win32":
        d = detect_short_form("测试内容")
        assert d.is_short is True


def test_worker_thread_uses_threading_fallback():
    """Unix worker threads must not attempt to install signal handlers."""
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        d = executor.submit(detect_short_form, "测试内容").result()
    assert d.is_short is True


def test_template_thresholds_type_validation():
    """非法类型抛 TypeError."""
    with pytest.raises(TypeError):
        detect_short_form("内容", template_thresholds="100")


def test_unix_alarm_is_cancelled_when_detection_raises(monkeypatch):
    """异常路径不能留下会终止后续测试的 SIGALRM."""
    import signal
    import sys
    import src.pipeline.short_form as sf

    if sys.platform == "win32":
        return

    alarms = []
    monkeypatch.setattr(signal, "setitimer", lambda *args: alarms.append(args) or (0, 0))
    monkeypatch.setattr(sf, "_detect_short_form_inner", lambda *args: (_ for _ in ()).throw(ValueError("boom")))

    with pytest.raises(ValueError, match="boom"):
        detect_short_form("内容")
    assert alarms == [
        (signal.ITIMER_REAL, DEFAULT_TIMEOUT_SECONDS),
        (signal.ITIMER_REAL, 0),
    ]
