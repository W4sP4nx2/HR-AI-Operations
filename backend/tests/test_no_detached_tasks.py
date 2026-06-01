"""Static guard: no fire-and-forget tasks in app code (BYOK contextvar safety).

The request-scoped BYOK key lives in a ``contextvars.ContextVar`` that the ASGI
middleware resets in its ``finally``. An un-awaited ``asyncio.create_task`` /
``ensure_future``, or a FastAPI ``BackgroundTasks``, copies the current context
(including the key) into a child that can **outlive that reset** — a cross-request
key-exposure boundary. The whole agentic fleet is kept synchronous-to-the-caller
specifically to avoid this, so none of these primitives may appear in app code.

This AST check fails the build if one is introduced. (``asyncio.to_thread`` is
allowed: it is always awaited, so the context copy is bounded by the call.)
"""

from __future__ import annotations

import ast
import pathlib

_FORBIDDEN_CALLS = {"create_task", "ensure_future"}  # asyncio fire-and-forget
_FORBIDDEN_NAMES = {"BackgroundTasks"}  # FastAPI deferred execution
_APP_DIRS = ["agents", "pipelines", "services", "core", "api", "models", "scripts"]


def _violations(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _FORBIDDEN_CALLS:
                found.append((node.lineno, node.func.attr))
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_NAMES:
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _FORBIDDEN_NAMES:
                    found.append((node.lineno, alias.name))
    return found


def test_no_fire_and_forget_tasks_in_app_code() -> None:
    base = pathlib.Path(__file__).resolve().parent.parent
    offenders: dict[str, list[tuple[int, str]]] = {}
    for d in _APP_DIRS:
        for py in (base / d).rglob("*.py"):
            if "__pycache__" in str(py):
                continue
            v = _violations(py)
            if v:
                offenders[str(py.relative_to(base))] = v
    assert not offenders, (
        "Fire-and-forget task / BackgroundTasks found — these copy the request "
        f"contextvar (BYOK key) into a child that can outlive its reset:\n{offenders}"
    )
