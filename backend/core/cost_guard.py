"""Pre-API token and cost controls for zero-waste inference."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class TokenBudgetExceeded(ValueError):
    """Raised when a request is rejected before any provider call."""

    def __init__(self, input_tokens: int, limit: int) -> None:
        super().__init__(
            f"Prompt exceeds budget: estimated {input_tokens} input tokens, limit {limit}"
        )
        self.input_tokens = input_tokens
        self.limit = limit


@dataclass(frozen=True)
class TokenBudget:
    input_tokens: int
    max_input_tokens: int
    max_output_tokens: int
    estimated_total_tokens: int


class TokenBudgetGuard:
    """Estimate tokens locally and reject infeasible requests before API spend."""

    def __init__(self, max_input_tokens: int = 4000, max_output_tokens: int = 1000) -> None:
        self.max_input_tokens = max(1, max_input_tokens)
        self.max_output_tokens = max(1, max_output_tokens)
        self._encoder = self._load_encoder()

    def estimate_text_tokens(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder is not None:
            return len(self._encoder.encode(text))
        # Deterministic fallback: roughly OpenAI/Llama token-like chunks without a
        # network or model file dependency. Conservative enough for pre-flight.
        return max(1, len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE)))

    def estimate_messages(self, messages: list[dict[str, Any]]) -> int:
        return sum(
            self.estimate_text_tokens(self._message_content_text(message)) for message in messages
        )

    def validate_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        max_output_tokens: int | None = None,
    ) -> TokenBudget:
        output_tokens = max_output_tokens or self.max_output_tokens
        input_tokens = self.estimate_messages(messages)
        if input_tokens > self.max_input_tokens:
            raise TokenBudgetExceeded(input_tokens, self.max_input_tokens)
        return TokenBudget(
            input_tokens=input_tokens,
            max_input_tokens=self.max_input_tokens,
            max_output_tokens=output_tokens,
            estimated_total_tokens=input_tokens + output_tokens,
        )

    def validate_budget(
        self,
        messages: list[dict[str, Any]],
        *,
        max_output_tokens: int | None = None,
    ) -> bool:
        """Compatibility wrapper for call sites that only need pass/fail."""
        self.validate_messages(messages, max_output_tokens=max_output_tokens)
        return True

    def validate_text(self, text: str, *, max_output_tokens: int | None = None) -> TokenBudget:
        return self.validate_messages(
            [{"role": "user", "content": text}],
            max_output_tokens=max_output_tokens,
        )

    def _message_content_text(self, message: dict[str, Any]) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    value = item.get("text")
                    if isinstance(value, str):
                        parts.append(value)
            return "\n".join(parts)
        return str(content)

    def _load_encoder(self):
        try:
            import tiktoken

            return tiktoken.get_encoding("cl100k_base")
        except Exception:  # noqa: BLE001 - optional dependency; fallback is deterministic
            return None
