"""Locust load test for the RAG chat path.

Simulates employees asking policy questions (the RAG-heavy path) plus lighter
case browsing, to measure p95 latency with vs. without RAG (toggle ENABLE_RAG on
the server) and across vector backends (pgvector vs. degraded).

Run (server must be up on :8000):

    pip install locust
    # register/login once to get a token, export it, then:
    locust -f tests/load/locustfile.py --host http://localhost:8000 \
           --users 50 --spawn-rate 5 --run-time 2m --headless

Targets (see README): RAG retrieval < 100ms, full chat response < 3s p95.
Auth: set HR_TOKEN in the environment (a viewer token is enough for chat/cases),
or leave empty to run against advisory mode (AUTH_ENFORCE=false).
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

TOKEN = os.environ.get("HR_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

QUESTIONS = [
    "What is the remote work policy?",
    "How many vacation days do I get?",
    "What is the parental leave entitlement?",
    "How do I claim travel expenses?",
    "What is the policy on reporting harassment?",
    "When is open enrollment for benefits?",
]


class EmployeeUser(HttpUser):
    """A typical employee: mostly asks the assistant, occasionally checks cases."""

    wait_time = between(1, 3)

    @task(3)
    def chat_policy(self) -> None:
        self.client.post(
            "/chat",
            json={"message": random.choice(QUESTIONS)},
            headers=HEADERS,
            name="/chat (policy Q&A)",
        )

    @task(1)
    def view_cases(self) -> None:
        self.client.get("/cases", headers=HEADERS, name="/cases")

    @task(1)
    def health(self) -> None:
        self.client.get("/health", name="/health")
