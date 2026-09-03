from src.pipeline.retry import RetryBudget, RetryClass, classify_failure


def test_budget_is_shared_and_fail_closed():
    budget = RetryBudget(max_llm_calls=1)
    assert budget.consume()
    assert not budget.consume()


def test_failure_classification():
    assert classify_failure(TimeoutError()) == RetryClass.PROVIDER
    assert classify_failure(ValueError("bad format")) == RetryClass.FORMAT
