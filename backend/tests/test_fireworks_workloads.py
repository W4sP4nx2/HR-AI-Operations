"""No-key Fireworks workload, routing, and request-contract tests."""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from core.fireworks import (
    RESUME_SCHEMA,
    affinity_token,
    build_batch_jsonl,
    build_chat_body,
    build_resume_vision_body,
    choose_serving_mode,
    client_headers,
    fireworks_manifest,
    is_scale_up_exception,
    is_scale_up_response,
    prune_tool_schemas,
    scale_up_delays,
)


@pytest.fixture
def allowed_models(monkeypatch):
    monkeypatch.setenv("ALLOWED_MODELS", "tenant/fast-8b,tenant/vision-70b")
    return ["tenant/fast-8b", "tenant/vision-70b"]


def test_serving_mode_uses_serverless_batch_and_dedicated_without_credentials():
    assert choose_serving_mode() == "serverless"
    assert choose_serving_mode(asynchronous=True) == "batch"
    assert choose_serving_mode(requires_reserved_capacity=True) == "dedicated"
    assert choose_serving_mode(custom_or_fine_tuned_model=True) == "dedicated"


def test_affinity_is_stable_and_does_not_leak_the_session_id():
    token = affinity_token("employee@example.com/session-123")
    assert token == affinity_token("employee@example.com/session-123")
    assert "employee" not in token
    headers = client_headers("employee@example.com/session-123")
    assert headers["x-session-affinity"] == token
    assert headers["Fireworks-Annotations"] == (
        "team=hr,project=hr-command-center,environment=development"
    )
    assert client_headers("") == {
        "Fireworks-Annotations": "team=hr,project=hr-command-center,environment=development"
    }


def test_structured_chat_body_is_bounded_and_allowlisted(allowed_models):
    body = build_chat_body(
        model_id=allowed_models[0],
        messages=[{"role": "user", "content": "Return JSON."}],
        schema_name="ResumeExtraction",
        json_schema=RESUME_SCHEMA,
        session_id="chat-123",
        top_k=20,
        top_p=0.9,
    )
    assert body["model"] == allowed_models[0]
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["user"].startswith("hrcc-")
    assert body["top_k"] == 20
    assert body["top_p"] == 0.9
    assert body["x_preflight_budget"]["input_tokens"] > 0

    with pytest.raises(ValueError, match="ALLOWED_MODELS"):
        build_chat_body(
            model_id="unapproved/model",
            messages=[{"role": "user", "content": "hello"}],
        )


def test_chat_body_requires_static_system_context_first(allowed_models):
    with pytest.raises(ValueError, match="system prompt must be first"):
        build_chat_body(
            model_id=allowed_models[0],
            messages=[
                {"role": "user", "content": "Question first."},
                {"role": "system", "content": "Static instructions too late."},
            ],
        )


def test_tool_schema_pruning_removes_unused_tools(allowed_models):
    tools = [
        {"type": "function", "function": {"name": "search_policy", "parameters": {}}},
        {"type": "function", "function": {"name": "create_case", "parameters": {}}},
    ]

    assert prune_tool_schemas(tools, ["search_policy"]) == [tools[0]]
    body = build_chat_body(
        model_id=allowed_models[0],
        messages=[{"role": "system", "content": "Static."}, {"role": "user", "content": "Q"}],
        tools=tools,
        allowed_tool_names=["search_policy"],
    )
    assert body["tools"] == [tools[0]]


def test_resume_vision_body_places_images_before_text(allowed_models):
    body = build_resume_vision_body(
        model_id=allowed_models[1],
        image_urls=["data:image/png;base64,AAAA", "https://example.invalid/page-2.png"],
    )
    content = body["messages"][0]["content"]
    assert [part["type"] for part in content] == ["image_url", "image_url", "text"]
    assert body["temperature"] == 0.0
    assert body["top_k"] == 20
    assert body["response_format"]["json_schema"]["name"] == "ResumeExtraction"
    assert body["response_format"]["json_schema"]["strict"] is True

    with pytest.raises(ValueError, match="at most 30"):
        build_resume_vision_body(
            model_id=allowed_models[1],
            image_urls=["https://example.invalid/page.png"] * 31,
        )
    with pytest.raises(ValueError, match="base64"):
        build_resume_vision_body(
            model_id=allowed_models[1],
            image_urls=["data:image/png,not-base64"],
        )


@pytest.mark.asyncio
async def test_direct_vision_execution_keeps_fireworks_top_k_in_extra_body(
    monkeypatch, allowed_models
):
    import openai

    captured = {}

    class Completions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "name": None,
                                    "email": None,
                                    "phone": None,
                                    "skills": [],
                                    "experience": [],
                                    "education": [],
                                    "warnings": [],
                                }
                            )
                        )
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=Completions())

        async def close(self):
            return None

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fixture-fireworks-key-not-real")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")

    from core.llm_factory import run_fireworks_chat_body

    body = build_resume_vision_body(
        model_id=allowed_models[1],
        image_urls=["data:image/png;base64,AAAA"],
    )
    result = await run_fireworks_chat_body(body)

    assert json.loads(result)["warnings"] == []
    assert "top_k" not in captured
    assert captured["extra_body"] == {"top_k": 20}
    assert captured["response_format"]["json_schema"]["strict"] is True


@pytest.mark.asyncio
async def test_direct_vision_execution_rejects_uncertified_response(monkeypatch, allowed_models):
    import openai

    class Completions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"name":"Jane","email":"jane@example.com"}'
                        )
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **_kwargs):
            self.chat = SimpleNamespace(completions=Completions())

        async def close(self):
            return None

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fixture-fireworks-key-not-real")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")

    from core.llm_factory import run_fireworks_chat_body

    body = build_resume_vision_body(
        model_id=allowed_models[1],
        image_urls=["data:image/png;base64,AAAA"],
    )
    with pytest.raises(RuntimeError, match="failed certifier schema validation"):
        await run_fireworks_chat_body(body)


def test_sampling_parameters_reject_out_of_range_values(allowed_models):
    with pytest.raises(ValueError, match="top_k"):
        build_chat_body(
            model_id=allowed_models[0],
            messages=[{"role": "user", "content": "hello"}],
            top_k=101,
        )
    with pytest.raises(ValueError, match="top_p"):
        build_chat_body(
            model_id=allowed_models[0],
            messages=[{"role": "user", "content": "hello"}],
            top_p=1.1,
        )


def test_exact_gemma_routes_only_on_deploy_on_demand(monkeypatch) -> None:
    from core.fireworks import GEMMA_4_26B_A4B_IT, gemma_route_status
    from core.llm_factory import pick_model_for_role

    batch_model = "accounts/example/models/serverless-batch"
    models = [batch_model, GEMMA_4_26B_A4B_IT]
    monkeypatch.setenv("ALLOWED_MODELS", ",".join(models))
    monkeypatch.setenv("FIREWORKS_GEMMA_MODEL", GEMMA_4_26B_A4B_IT)
    monkeypatch.setenv("FIREWORKS_SERVING_MODE", "serverless")
    assert pick_model_for_role("multimodal synthesis", models) != GEMMA_4_26B_A4B_IT

    monkeypatch.setenv("FIREWORKS_SERVING_MODE", "deploy_on_demand")
    assert pick_model_for_role("multimodal synthesis", models) == GEMMA_4_26B_A4B_IT
    status = gemma_route_status()
    assert status["allowlisted"] is True
    assert status["serverless_supported"] is False


def test_batch_jsonl_has_unique_ids_and_request_bodies(allowed_models):
    payload = build_batch_jsonl(
        [
            {"custom_id": "resume-1", "prompt": "Extract resume one as JSON."},
            {"custom_id": "resume-2", "prompt": "Extract resume two as JSON."},
        ],
        model_id=allowed_models[0],
        system_prompt="Static instructions first.",
    )
    rows = [json.loads(line) for line in payload.splitlines()]
    assert [row["custom_id"] for row in rows] == ["resume-1", "resume-2"]
    assert all("model" not in row["body"] for row in rows)
    assert all("x_preflight_budget" not in row["body"] for row in rows)
    assert all(
        row["body"]["messages"][0]["content"] == "Static instructions first." for row in rows
    )

    with pytest.raises(ValueError, match="duplicate"):
        build_batch_jsonl(
            [
                {"custom_id": "same", "prompt": "one"},
                {"custom_id": "same", "prompt": "two"},
            ],
            model_id=allowed_models[0],
            system_prompt="system",
        )


def test_scale_from_zero_detection_and_backoff():
    payload = {"error": {"code": "DEPLOYMENT_SCALING_UP"}}
    assert is_scale_up_response(503, payload) is True
    assert is_scale_up_response(503, {"code": "DEPLOYMENT_SCALING_UP"}) is True
    assert is_scale_up_response(500, payload) is False

    class ScalingError(Exception):
        status_code = 503
        body = payload

    assert is_scale_up_exception(ScalingError()) is True
    assert scale_up_delays(5) == [5.0, 7.5, 11.25, 16.875, 25.3125]
    assert scale_up_delays(3, initial_seconds=50) == [50, 60.0, 60.0]


def test_manifest_is_secret_free_and_use_case_complete(monkeypatch, allowed_models):
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "fixture-fireworks-key-not-real")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "https://example.invalid/v1")
    manifest = fireworks_manifest()
    use_cases = {item["id"] for item in manifest["use_cases"]}
    assert manifest["configuration"]["allowed_model_count"] == 2
    assert manifest["configuration"]["credentials_exposed"] is False
    assert "cost_attribution" in manifest["runtime_telemetry"]
    assert "cache_hit_rate" in manifest["runtime_telemetry"]
    assert "prefilter_skip_rate" in manifest["runtime_telemetry"]
    assert manifest["runtime_telemetry"]["cost_router"]["model_selection"] == "ALLOWED_MODELS only"
    assert manifest["batch_async_contract"]["reference"]["status"] == "pending"
    assert manifest["batch_async_contract"]["pending_warning_after_minutes"] == 30
    assert "fixture-fireworks-key-not-real" not in json.dumps(manifest)
    assert {
        "policy_qa",
        "case_triage",
        "resume_parsing",
        "bulk_resume_processing",
        "agent_evaluation",
        "fine_tuned_hr_extraction",
    } <= use_cases


@pytest.mark.skipif(
    not (
        os.environ.get("FIREWORKS_API_KEY")
        and os.environ.get("FIREWORKS_BASE_URL")
        and os.environ.get("ALLOWED_MODELS")
    ),
    reason="live Fireworks path requires key, base URL and allowlisted model",
)
@pytest.mark.asyncio
async def test_live_fireworks_structured_round_trip():
    from core.fireworks import configured_models
    from core.llm_factory import pick_model_for_role, run_fireworks_chat_body

    model = pick_model_for_role("triage", configured_models())
    body = build_chat_body(
        model_id=model,
        messages=[
            {
                "role": "user",
                "content": "Return JSON with status exactly equal to ok.",
            }
        ],
        max_tokens=32,
        temperature=0.0,
        schema_name="SmokeResult",
        json_schema={
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["ok"]}},
            "required": ["status"],
            "additionalProperties": False,
        },
        top_k=1,
    )
    result = json.loads(await run_fireworks_chat_body(body))

    assert result == {"status": "ok"}
