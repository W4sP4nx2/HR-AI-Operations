"""Hierarchical CrewAI systems are explicit, governed, and executable offline."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agents.hierarchical_crew import (
    CrewCapabilityUnavailable,
    build_hierarchical_crewai,
    hierarchical_system_manifest,
    run_hierarchical_system,
)
from agents.langsmith_cost_tracker import HierarchicalTrace, trace_payload_metadata
from api.main import app


def test_manifest_exposes_two_manager_plus_two_worker_systems() -> None:
    manifest = hierarchical_system_manifest()

    assert manifest["architecture"] == "hierarchical"
    assert manifest["product_boundary"] == "single_orchestrator_with_bounded_crewai_subtask"
    assert manifest["context_source"] == "validated_endpoint_parameters"
    assert manifest["external_repository_fetch"] is False
    assert manifest["system_count"] == 2
    assert {item["system_id"] for item in manifest["systems"]} == {
        "resume_review",
        "policy_case_resolution",
    }
    for system in manifest["systems"]:
        assert system["process"] == "hierarchical"
        assert system["manager_agent"]["allow_delegation"] is True
        assert len(system["worker_agents"]) == 2
        assert all(worker["allow_delegation"] is False for worker in system["worker_agents"])
        assert "human" in system["human_decision_boundary"].lower()


@pytest.mark.asyncio
async def test_resume_hierarchy_runs_two_workers_and_blinds_pii() -> None:
    envelope = await run_hierarchical_system(
        "resume_review",
        {
            "job_description": "Python Docker Kubernetes",
            "resume": "Name: Jane Doe. Built Python and Docker services. jane@example.com",
        },
        mode="deterministic",
    )

    assert envelope.certification.is_valid is True
    assert envelope.payload["execution_mode"] == "deterministic_fallback"
    assert envelope.payload["process"] == "hierarchical"
    assert envelope.payload["human_review_required"] is True
    assert envelope.metadata["hitl_status"] == "awaiting_approval"
    assert envelope.metadata["human_review_task_id"].startswith("TASK-")
    assert [step["agent_id"] for step in envelope.payload["steps"]] == [
        "resume_evidence_analyst",
        "fairness_policy_guard",
    ]
    serialized = str(envelope.model_dump(mode="json"))
    assert "Jane Doe" not in serialized
    assert "jane@example.com" not in serialized
    assert "matched_skills=Docker,Python" in serialized
    assert envelope.payload["handoffs"][-1]["target"] == "human_reviewer"
    assert envelope.payload["handoffs"][-1]["status"] == "awaiting_human_review"


@pytest.mark.asyncio
async def test_policy_case_hierarchy_escalates_urgent_ungrounded_case() -> None:
    envelope = await run_hierarchical_system(
        "policy_case_resolution",
        {"ticket": "Urgent safety issue in the office"},
        mode="deterministic",
    )

    assert envelope.certification.is_valid is True
    assert envelope.payload["status"] == "review_required"
    assert envelope.payload["human_review_required"] is True
    assert "category=URGENT" in str(envelope.payload)
    assert "policy_context_present=false" in str(envelope.payload)


@pytest.mark.asyncio
async def test_explicit_live_mode_fails_clearly_when_runtime_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr("agents.crewai_adapter.crewai_available", lambda: False)
    monkeypatch.setattr("core.runtime_key.llm_active", lambda: False)

    with pytest.raises(CrewCapabilityUnavailable, match="CrewAI package"):
        await run_hierarchical_system(
            "policy_case_resolution",
            {"ticket": "Question about PTO policy"},
            mode="live",
        )


def test_builder_uses_real_hierarchical_contract(monkeypatch) -> None:
    module = types.ModuleType("crewai")

    class FakeProcess:
        hierarchical = "hierarchical-process"

    class FakeAgent:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeTask:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeCrew:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    module.Agent = FakeAgent
    module.Crew = FakeCrew
    module.Process = FakeProcess
    module.Task = FakeTask
    monkeypatch.setitem(sys.modules, "crewai", module)

    crew = build_hierarchical_crewai("resume_review", llm=object())

    assert crew.kwargs["process"] == FakeProcess.hierarchical
    assert crew.kwargs["manager_agent"].kwargs["allow_delegation"] is True
    assert len(crew.kwargs["agents"]) == 2
    assert all(agent.kwargs["allow_delegation"] is False for agent in crew.kwargs["agents"])
    assert len(crew.kwargs["tasks"]) == 1
    assert "both specialists" in crew.kwargs["tasks"][0].kwargs["description"]


def test_agent_modules_do_not_construct_provider_clients() -> None:
    agents_dir = Path(__file__).parents[1] / "agents"
    source = "\n".join(path.read_text() for path in agents_dir.glob("*.py"))

    assert "from openai import" not in source
    assert "OpenAI(" not in source


def test_installed_crewai_builds_both_real_hierarchies(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("LLM_PROVIDER", "fireworks")
    monkeypatch.setenv("FIREWORKS_API_KEY", "test-key-test-key")
    monkeypatch.setenv("FIREWORKS_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("ALLOWED_MODELS", "test-model")

    original_anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    try:
        from crewai import Process

        for system_id in ("resume_review", "policy_case_resolution"):
            crew = build_hierarchical_crewai(system_id)
            assert crew.process == Process.hierarchical
            assert crew.manager_agent.allow_delegation is True
            assert len(crew.agents) == 2
            assert all(agent.allow_delegation is False for agent in crew.agents)
            assert type(crew.manager_agent.llm).__name__ == "OpenAICompatibleCrewLLM"
    finally:
        # CrewAI's import-time dotenv discovery may load a developer's backend
        # .env into os.environ. Do not let that third-party side effect leak
        # credentials or placeholders into later tests.
        if original_anthropic_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = original_anthropic_key


def test_langsmith_nested_trace_never_receives_raw_payload(monkeypatch) -> None:
    captured: list[object] = []
    run_trees = types.ModuleType("langsmith.run_trees")
    langsmith = types.ModuleType("langsmith")

    class FakeRun:
        def __init__(self, **kwargs):
            captured.append(kwargs)

        def post(self):
            captured.append("post")

        def create_child(self, **kwargs):
            captured.append(kwargs)
            return self

        def end(self, **kwargs):
            captured.append(kwargs)

        def patch(self):
            captured.append("patch")

    run_trees.RunTree = FakeRun
    monkeypatch.setitem(sys.modules, "langsmith", langsmith)
    monkeypatch.setitem(sys.modules, "langsmith.run_trees", run_trees)
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-key-test-key")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    tracer = HierarchicalTrace(
        name="crewai_resume_review",
        orchestration_id="trace-1",
        inputs={"resume": "Jane jane@example.com"},
    )
    tracer.record_step("resume_evidence_analyst", {"summary": "Jane matched Python"})
    tracer.finish({"summary": "Jane requires review"})

    serialized = str(captured)
    assert "jane@example.com" not in serialized
    assert "Jane matched" not in serialized
    assert "raw_payload_sent" in serialized
    assert trace_payload_metadata({"ticket": "secret"})["top_level_keys"] == ["ticket"]


def test_hierarchical_api_exposes_and_runs_both_systems(monkeypatch) -> None:
    from core.runtime_settings import runtime_settings

    async def _skip_persisted_operator_settings():
        return runtime_settings.public()

    # This endpoint test is about the crew contract, not a developer's local
    # encrypted Settings row. Prevent app lifespan from importing that state
    # into later tests in the same process.
    monkeypatch.setattr(runtime_settings, "load", _skip_persisted_operator_settings)
    client = TestClient(app)

    manifest = client.get("/crews/hierarchical").json()
    assert manifest["success"] is True
    assert manifest["data"]["system_count"] == 2

    run = client.post(
        "/crews/hierarchical/policy_case_resolution/run",
        json={"mode": "deterministic", "inputs": {"ticket": "Urgent safety incident"}},
    ).json()
    assert run["success"] is True
    assert run["data"]["certification"]["is_valid"] is True
    assert run["data"]["payload"]["execution_mode"] == "deterministic_fallback"
    assert run["data"]["metadata"]["hitl_status"] == "awaiting_approval"
    assert run["data"]["metadata"]["human_review_task_id"].startswith("TASK-")


def test_resume_batch_endpoint_returns_202_and_provider_ids(monkeypatch) -> None:
    model_id = "accounts/example/models/serverless-batch-model"

    async def fake_submit(payload: bytes, *, model_id: str, job_id: str):
        assert payload
        return {
            "job_id": job_id,
            "input_dataset_id": f"{job_id}-input",
            "output_dataset_id": f"{job_id}-output",
        }

    monkeypatch.setenv("ALLOWED_MODELS", model_id)
    monkeypatch.setenv("FIREWORKS_BATCH_MODEL", model_id)
    monkeypatch.setattr("services.fireworks_batch.submit_jsonl_batch", fake_submit)
    client = TestClient(app)

    response = client.post(
        "/crews/hierarchical/resume_review/batch",
        json={
            "job_description": "Python engineer",
            "resumes": [{"resume_id": "candidate-1", "resume_text": "Built Python APIs"}],
        },
    )
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["accepted"] is True
    assert data["http_status"] == 202
    assert data["records"] == 1
    assert data["agent_registry_match"] == "resume_screener_agent"
    assert data["job_id"].startswith("batch-")
