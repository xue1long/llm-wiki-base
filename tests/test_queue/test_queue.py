# ruflo-kb/tests/test_queue/test_queue.py
from src.queue import generate_task_id, get_queue, pause_queue, resume_queue
from src.utils.idempotency import get_idempotency_cache


def setup_function(_):
    get_idempotency_cache().clear()


def test_generate_task_id():
    """Test task ID generation"""
    id1 = generate_task_id()
    id2 = generate_task_id()

    assert id1.startswith("kb-")
    assert id2.startswith("kb-")
    assert id1 != id2  # Should be unique


def test_get_queue():
    """Test get_queue returns a copy"""
    queue1 = get_queue()
    queue2 = get_queue()
    assert queue1 == queue2
    # Should be a copy, not the same reference
    assert queue1 is not queue2


def test_pause_resume():
    """Test queue pause and resume"""
    pause_queue()
    resume_queue()  # Should not raise
