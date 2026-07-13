"""Onboarding Orchestrator agent built with LangGraph.

Pipeline of steps:
    validate_new_hire_data -> create_accounts -> assign_training
    -> [HUMAN CHECKPOINT] -> send_welcome_email -> notify_manager

State is persisted to SQLite between steps. Before ``send_welcome_email`` the
agent pauses and creates a human-in-the-loop task; a WebSocket event is emitted
to the frontend (via the broadcaster callback). If any step fails it is logged
to the audit table and the run pauses for human review.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypedDict

from core.memory import memory

AGENT_NAME = "onboarding_agent"

# Optional broadcaster injected by the API layer to emit WebSocket events.
Broadcaster = Callable[[dict[str, Any]], Awaitable[None]]


class OnboardingState(TypedDict, total=False):
    """State threaded through the onboarding workflow."""

    new_hire: dict[str, Any]
    accounts: list[str]
    training: list[str]
    welcome_sent: bool
    manager_notified: bool
    paused_at: str
    errors: list[str]


class OnboardingAgent:
    """Orchestrates new-hire onboarding with a human approval checkpoint."""

    def __init__(self, broadcaster: Broadcaster | None = None) -> None:
        """Initialise the agent.

        Args:
            broadcaster: Optional async callable used to emit WebSocket events.
        """
        self._broadcast = broadcaster
        self._graph = self._build_graph()

    def set_broadcaster(self, broadcaster: Broadcaster) -> None:
        """Attach a WebSocket broadcaster after construction."""
        self._broadcast = broadcaster

    # -- individual steps -------------------------------------------------
    def _validate(self, state: OnboardingState) -> OnboardingState:
        """Validate required new-hire fields; record errors if missing."""
        hire = state.get("new_hire", {})
        required = ["name", "email", "department", "manager"]
        missing = [f for f in required if not hire.get(f)]
        errors = list(state.get("errors", []))
        if missing:
            errors.append(f"missing fields: {', '.join(missing)}")
        return {**state, "errors": errors}

    def _create_accounts(self, state: OnboardingState) -> OnboardingState:
        """Provision system accounts for the new hire."""
        hire = state.get("new_hire", {})
        email = hire.get("email", "unknown@example.com")
        accounts = [f"sso:{email}", f"email:{email}", f"hris:{hire.get('name', 'new')}"]
        return {**state, "accounts": accounts}

    def _assign_training(self, state: OnboardingState) -> OnboardingState:
        """Assign role-appropriate onboarding training modules."""
        dept = state.get("new_hire", {}).get("department", "general")
        training = ["security-awareness", "code-of-conduct", f"{dept}-101"]
        return {**state, "training": training}

    def _send_welcome_email(self, state: OnboardingState) -> OnboardingState:
        """Send the welcome email (runs only after human approval)."""
        return {**state, "welcome_sent": True}

    def _notify_manager(self, state: OnboardingState) -> OnboardingState:
        """Notify the hiring manager that onboarding is complete."""
        return {**state, "manager_notified": True}

    def _build_graph(self):
        """Compile a LangGraph workflow up to the human checkpoint."""
        try:
            from langgraph.graph import END, StateGraph

            graph = StateGraph(OnboardingState)
            graph.add_node("validate", self._validate)
            graph.add_node("create_accounts", self._create_accounts)
            graph.add_node("assign_training", self._assign_training)
            graph.set_entry_point("validate")
            graph.add_edge("validate", "create_accounts")
            graph.add_edge("create_accounts", "assign_training")
            graph.add_edge("assign_training", END)
            return graph.compile()
        except Exception:  # noqa: BLE001
            return None

    async def _emit(self, event: dict[str, Any]) -> None:
        """Emit a WebSocket event if a broadcaster is attached."""
        if self._broadcast is not None:
            await self._broadcast(event)

    # -- public API -------------------------------------------------------
    async def start(self, new_hire: dict[str, Any]) -> dict[str, Any]:
        """Run onboarding up to the human-in-the-loop checkpoint.

        Args:
            new_hire: Dict describing the new hire (name, email, department,
                manager).

        Returns:
            A dict describing the run outcome: either ``status='paused'`` with a
            ``task`` awaiting approval, or ``status='error'`` if a step failed.
        """
        await memory.upsert_agent(AGENT_NAME, status="running", last_action="onboarding started")
        state: OnboardingState = {"new_hire": new_hire, "errors": []}

        try:
            if self._graph is not None:
                state = await asyncio.to_thread(self._graph.invoke, state)
            else:
                state = self._validate(state)
                state = self._create_accounts(state)
                state = self._assign_training(state)

            # If validation/earlier steps produced errors, pause for review.
            if state.get("errors"):
                await memory.log_audit(
                    AGENT_NAME,
                    "onboarding",
                    new_hire,
                    {"errors": state["errors"]},
                    "error",
                )
                task = await memory.create_agent_task(
                    AGENT_NAME,
                    step="error_review",
                    context=f"Onboarding errors: {state['errors']}",
                    state=dict(state),
                )
                await memory.upsert_agent(
                    AGENT_NAME, status="error", last_action="paused: validation errors"
                )
                await self._emit({"type": "onboarding_error", "agent": AGENT_NAME, "task": task})
                return {"status": "error", "task": task, "state": state}

            # Human-in-the-loop checkpoint before send_welcome_email.
            task = await memory.create_agent_task(
                AGENT_NAME,
                step="send_welcome_email",
                context=(
                    f"Ready to send welcome email to {new_hire.get('email')} "
                    f"with accounts {state.get('accounts')} and training "
                    f"{state.get('training')}."
                ),
                state=dict(state),
            )
            await memory.log_audit(
                AGENT_NAME,
                "onboarding",
                new_hire,
                {"checkpoint": "send_welcome_email"},
                "paused",
            )
            await memory.upsert_agent(
                AGENT_NAME,
                status="idle",
                last_action="awaiting approval: send_welcome_email",
                increment_runs=True,
            )
            await self._emit(
                {
                    "type": "approval_required",
                    "agent": AGENT_NAME,
                    "step": "send_welcome_email",
                    "task": task,
                }
            )
            return {"status": "paused", "task": task, "state": state}
        except Exception as exc:  # noqa: BLE001
            await memory.log_audit(AGENT_NAME, "onboarding", new_hire, {"error": str(exc)}, "error")
            await memory.upsert_agent(AGENT_NAME, status="error", last_action=str(exc))
            raise

    async def resume_after_approval(
        self, state: dict[str, Any], approved: bool, reason: str = ""
    ) -> dict[str, Any]:
        """Continue the workflow after a human approves or rejects.

        Args:
            state: The persisted onboarding state captured at the checkpoint.
            approved: Whether a human approved the ``send_welcome_email`` step.
            reason: Optional rejection reason.

        Returns:
            The final state dict.
        """
        if not approved:
            await memory.log_audit(AGENT_NAME, "onboarding", state, {"rejected": reason}, "error")
            await self._emit({"type": "onboarding_rejected", "agent": AGENT_NAME, "reason": reason})
            return {**state, "welcome_sent": False, "rejected_reason": reason}

        state = self._send_welcome_email(state)  # type: ignore[arg-type]
        state = self._notify_manager(state)  # type: ignore[arg-type]
        await memory.log_audit(
            AGENT_NAME,
            "onboarding",
            state.get("new_hire", {}),
            {"completed": True},
            "success",
        )
        await memory.upsert_agent(AGENT_NAME, status="idle", last_action="onboarding completed")
        await self._emit({"type": "onboarding_completed", "agent": AGENT_NAME})
        return state


onboarding_agent = OnboardingAgent()
