"""Short-form content detection — classify content as memory (short) or concept.

Platform-compatible timeout: threading.ThreadPoolExecutor on Windows,
signal.alarm on Unix (P13 + P26 stress-test hardening).
"""
import re
import sys
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_CHAR_THRESHOLD = 200
DEFAULT_STEP_THRESHOLD = 3
DEFAULT_TIMEOUT_SECONDS = 5


@dataclass
class ShortFormDecision:
    is_short: bool
    processing_depth: str  # "concept" | "memory"
    char_count: int
    step_count: int
    template_overridden: bool = False
    timed_out: bool = False


_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_STEPS_RE = re.compile(
    r"^\d+\."
    r"|第[一二三四五六七八九十]+[步点节]"
    r"|第\d+[步点节]"
    r"|首先|其次|然后|最后",
    re.MULTILINE,
)


def _count_chinese_chars(content: str) -> int:
    return len(_CJK_RE.findall(content))


def _count_steps(content: str) -> int:
    return len(_STEPS_RE.findall(content))


def _detect_short_form_inner(
    content: str,
    char_threshold: int,
    step_threshold: int,
    template_thresholds: Optional[dict],
) -> ShortFormDecision:
    """Inner detection logic, isolated for timeout wrapper."""
    overridden = False
    ct = char_threshold
    st = step_threshold
    if template_thresholds is not None:
        if not isinstance(template_thresholds, dict):
            raise TypeError(
                f"template_thresholds must be dict, got {type(template_thresholds)}"
            )
        if "chars" in template_thresholds:
            ct = template_thresholds["chars"]
            overridden = True
        if "steps" in template_thresholds:
            st = template_thresholds["steps"]
            overridden = True

    chars = _count_chinese_chars(content)
    steps = _count_steps(content)
    is_short = chars < ct or steps < st
    return ShortFormDecision(
        is_short=is_short,
        processing_depth="memory" if is_short else "concept",
        char_count=chars,
        step_count=steps,
        template_overridden=overridden,
    )


# Module-level shared executor for batch reuse (P26).
_SHARED_EXECUTOR = None


def _get_shared_executor():
    global _SHARED_EXECUTOR
    import concurrent.futures

    if _SHARED_EXECUTOR is None or _SHARED_EXECUTOR._shutdown:
        _SHARED_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="short-form-detect"
        )
    return _SHARED_EXECUTOR


def detect_short_form(
    content: str,
    *,
    char_threshold: int = DEFAULT_CHAR_THRESHOLD,
    step_threshold: int = DEFAULT_STEP_THRESHOLD,
    template_thresholds: Optional[dict] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ShortFormDecision:
    """Detect whether content is short-form (memory) or standard (concept).

    Falls back to 'concept' on timeout.
    Platform-compatible: threading pool on Windows, signal.alarm on Unix.
    """
    if sys.platform == "win32":
        return _detect_with_threading_timeout(
            content, char_threshold, step_threshold, template_thresholds, timeout
        )

    # Unix: use a real-valued interval so sub-second timeouts work in tests
    # and callers; ``signal.alarm`` truncates values below one second to zero.
    import signal

    def _timeout_handler(signum, frame):
        raise TimeoutError("detect_short_form timed out")

    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    try:
        signal.setitimer(signal.ITIMER_REAL, timeout)
        result = _detect_short_form_inner(
            content, char_threshold, step_threshold, template_thresholds
        )
        return result
    except TimeoutError:
        logger.warning(
            "detect_short_form timed out after %ss, falling back to concept",
            timeout,
        )
        return ShortFormDecision(
            is_short=False,
            processing_depth="concept",
            char_count=0,
            step_count=0,
            timed_out=True,
        )
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)


def _detect_with_threading_timeout(
    content: str,
    char_threshold: int,
    step_threshold: int,
    template_thresholds: Optional[dict],
    timeout: float,
) -> ShortFormDecision:
    """Fallback timeout implementation using thread pool (Windows compatible)."""
    import concurrent.futures

    executor = _get_shared_executor()
    future = executor.submit(
        _detect_short_form_inner,
        content,
        char_threshold,
        step_threshold,
        template_thresholds,
    )
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        logger.warning(
            "detect_short_form timed out after %ss, falling back to concept",
            timeout,
        )
        return ShortFormDecision(
            is_short=False,
            processing_depth="concept",
            char_count=0,
            step_count=0,
            timed_out=True,
        )
