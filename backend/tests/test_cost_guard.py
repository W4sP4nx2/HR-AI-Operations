"""Pre-API token budget checks reject expensive requests locally."""

from __future__ import annotations

import pytest

from core.cost_guard import TokenBudgetExceeded, TokenBudgetGuard


def test_token_budget_guard_accepts_small_prompt():
    budget = TokenBudgetGuard(max_input_tokens=20, max_output_tokens=5).validate_text(
        "What is the dental policy?",
        max_output_tokens=5,
    )

    assert budget.input_tokens <= 20
    assert budget.estimated_total_tokens == budget.input_tokens + 5


def test_token_budget_guard_rejects_large_prompt_before_provider_call():
    guard = TokenBudgetGuard(max_input_tokens=3, max_output_tokens=5)

    with pytest.raises(TokenBudgetExceeded, match="Prompt exceeds budget"):
        guard.validate_text("one two three four five six")
