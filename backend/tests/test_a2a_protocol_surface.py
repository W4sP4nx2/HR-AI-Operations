"""Proof tests for the two addressable Govern.ai A2A roles."""

from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app


def test_agent_cards_are_discoverable_and_governed() -> None:
    client = TestClient(app)
    extractor = client.get("/a2a/agents/resume_extractor/.well-known/agent-card.json")
    guard = client.get("/a2a/agents/policy_guard/.well-known/agent-card.json")

    assert extractor.status_code == 200
    assert guard.status_code == 200
    assert extractor.json()["name"] == "resume_extractor"
    assert guard.json()["governance"]["human_approval_required"] is True


def test_two_agent_handoff_is_independently_addressable_and_pii_safe() -> None:
    client = TestClient(app)
    extracted = client.post(
        "/a2a/agents/resume_extractor/rpc",
        json={
            "jsonrpc": "2.0",
            "id": "extract-1",
            "method": "message/send",
            "params": {
                "message": {
                    "text": "Name: Jordan Lee. Backend engineer with Python, FastAPI, and AWS.\n"
                    "Email: jordan@example.com"
                }
            },
        },
    )
    assert extracted.status_code == 200
    extracted_result = extracted.json()["result"]
    assert extracted_result["task"]["status"] == "completed"
    profile = extracted_result["task"]["artifacts"][0]["data"]
    assert "jordan@example.com" not in str(profile).lower()
    assert profile["candidate_ref"]

    governed = client.post(
        "/a2a/agents/policy_guard/rpc",
        json={
            "jsonrpc": "2.0",
            "id": "guard-1",
            "method": "message/send",
            "params": {"profile": profile},
        },
    )
    assert governed.status_code == 200
    governed_result = governed.json()["result"]
    task = governed_result["task"]
    assert task["status"] == "input-required"
    governed_profile = task["artifacts"][0]["data"]
    assert governed_profile["human_approval_required"] is True
    assert "reject_candidate" in governed_profile["forbidden_actions"]
    assert governed_result["trace_id"]


def test_a2a_rejects_unsupported_rpc_methods() -> None:
    client = TestClient(app)
    response = client.post(
        "/a2a/agents/resume_extractor/rpc",
        json={"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {}},
    )
    assert response.json()["error"]["code"] == -32601
