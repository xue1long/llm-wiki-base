import pytest

from src.pipeline.retry import RetryBudget, RetryClass, RetryExhausted, classify_failure


def test_budget_rejects_a_second_stage_call():
    budget = RetryBudget(max_llm_calls=1)
    budget.consume_or_raise()
    with pytest.raises(RetryExhausted):
        budget.consume_or_raise()


def test_budget_is_shared_and_fail_closed():
    budget = RetryBudget(max_llm_calls=1)
    assert budget.consume()
    assert not budget.consume()


def test_failure_classification():
    assert classify_failure(TimeoutError()) == RetryClass.PROVIDER
    assert classify_failure(ValueError("bad format")) == RetryClass.FORMAT
