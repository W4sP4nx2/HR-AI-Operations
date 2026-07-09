"""Live Fireworks smoke test.

Run only when the harness or operator has injected real Fireworks env:

  LLM_PROVIDER=fireworks FIREWORKS_API_KEY=... FIREWORKS_BASE_URL=... \
  ALLOWED_MODELS=... python -m scripts.fireworks_smoke
"""

from __future__ import annotations

import os

from core.embeddings import embedder
from core.llm_factory import run_text_completion
from core.runtime_key import llm_config_issues, llm_provider


def main() -> int:
    if llm_provider() != "fireworks":
        print("LLM_PROVIDER must be 'fireworks' for this smoke test")
        return 2

    issues = llm_config_issues()
    if issues:
        print("Fireworks config incomplete:")
        for issue in issues:
            print(f"- {issue}")
        return 2

    answer = run_text_completion(
        "Reply with exactly: OK",
        role="triage_smoke",
        max_tokens=8,
        temperature=0,
    )
    if not answer or "OK" not in answer.upper():
        print(f"chat smoke failed; response={answer!r}")
        return 1
    print("chat smoke ok")

    if (os.environ.get("EMBEDDING_PROVIDER") or "").lower() == "fireworks":
        vector = embedder.embed("Fireworks embedding smoke test")
        if not vector:
            print("embedding smoke failed; empty vector")
            return 1
        print(f"embedding smoke ok; dimension={len(vector)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
