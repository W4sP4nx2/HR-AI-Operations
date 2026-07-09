"""Live Fireworks smoke test.

Run only when the harness or operator has injected real Fireworks env:

  LLM_PROVIDER=fireworks FIREWORKS_API_KEY=... FIREWORKS_BASE_URL=... \
  ALLOWED_MODELS=... python -m scripts.fireworks_smoke
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.cost_attribution import (  # noqa: E402
    cost_attribution_snapshot,
    estimate_text_tokens,
    record_cost_event,
)
from core.embeddings import embedder  # noqa: E402
from core.llm_factory import run_text_completion  # noqa: E402
from core.runtime_key import llm_config_issues, llm_provider  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a controlled live Fireworks smoke test.")
    parser.add_argument(
        "--enable-cost-tracking",
        action="store_true",
        help="print zero-spend benchmark evidence and smoke-call cost attribution",
    )
    args = parser.parse_args(argv)

    if llm_provider() != "fireworks":
        print("LLM_PROVIDER must be 'fireworks' for this smoke test")
        return 2

    issues = llm_config_issues()
    if issues:
        print("Fireworks config incomplete:")
        for issue in issues:
            print(f"- {issue}")
        return 2

    prompt = "Reply with exactly: OK"
    if args.enable_cost_tracking:
        _print_cost_control_preflight()

    answer = run_text_completion(
        prompt,
        role="triage_smoke",
        max_tokens=8,
        temperature=0,
    )
    if not answer or "OK" not in answer.upper():
        print(f"chat smoke failed; response={answer!r}")
        return 1
    print("chat smoke ok")
    if args.enable_cost_tracking:
        _record_smoke_cost(prompt, answer)

    if (os.environ.get("EMBEDDING_PROVIDER") or "").lower() == "fireworks":
        vector = embedder.embed("Fireworks embedding smoke test")
        if not vector:
            print("embedding smoke failed; empty vector")
            return 1
        print(f"embedding smoke ok; dimension={len(vector)}")

    return 0


def _print_cost_control_preflight() -> None:
    from scripts.benchmark_cost_controls import run_ab_benchmark

    benchmark = run_ab_benchmark()
    isolated = run_ab_benchmark(
        disable_cache=True,
        disable_router=True,
        disable_prefilter=True,
    )
    print(
        "cost controls preflight ok: "
        f"reduction={benchmark['cost_reduction']:.1%}, "
        f"quality_delta={benchmark['quality_delta']:.3f}, "
        f"disabled_reduction={isolated['cost_reduction']:.1%}"
    )


def _record_smoke_cost(prompt: str, answer: str) -> None:
    attribution = record_cost_event(
        tier="economy",
        input_tokens=estimate_text_tokens(prompt),
        output_tokens=estimate_text_tokens(answer),
        provider_call=True,
    )
    print(
        "cost attribution smoke: "
        f"tier={attribution.tier}, "
        f"estimated_usd={attribution.cost_usd:.6f}, "
        f"input_tokens={attribution.input_tokens}, "
        f"output_tokens={attribution.output_tokens}"
    )
    print("cost attribution snapshot:")
    print(json.dumps(cost_attribution_snapshot(), indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
