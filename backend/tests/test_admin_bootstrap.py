"""Tests for concurrency-safe first-admin bootstrap in enforced deployments."""

from __future__ import annotations

import asyncio


def test_bootstrap_admin_creates_account_once(monkeypatch) -> None:
    from api import main

    class FakeMemory:
        created: list[dict] = []

        async def get_user_by_email(self, _email: str):
            return None

        async def create_user(self, **record):
            self.created.append(record)

    fake = FakeMemory()
    monkeypatch.setattr(main, "memory", fake)

    created = asyncio.run(
        main._ensure_bootstrap_admin("judge-admin@example.com", "strong-test-password")
    )

    assert created is True
    assert len(fake.created) == 1
    assert fake.created[0]["email"] == "judge-admin@example.com"
    assert fake.created[0]["role"] == "admin"
    assert fake.created[0]["password_hash"] != "strong-test-password"


def test_bootstrap_admin_tolerates_concurrent_unique_email_winner(monkeypatch) -> None:
    from api import main

    existing = {"id": "USR-winner", "email": "judge-admin@example.com", "role": "admin"}

    class RacingMemory:
        reads = 0

        async def get_user_by_email(self, _email: str):
            self.reads += 1
            return None if self.reads == 1 else existing

        async def create_user(self, **_record):
            raise main.IntegrityError("insert users", {}, Exception("duplicate email"))

    monkeypatch.setattr(main, "memory", RacingMemory())

    created = asyncio.run(
        main._ensure_bootstrap_admin("judge-admin@example.com", "strong-test-password")
    )

    assert created is False
