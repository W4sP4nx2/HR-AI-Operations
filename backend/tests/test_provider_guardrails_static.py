"""Static guardrails for provider migrations.

These checks turn the manual "grep for bypasses" review step into a regression
test. They intentionally scan only runtime code, not tests or docs.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def _runtime_python_files() -> list[Path]:
    runtime_dirs = (
        "agents",
        "api",
        "core",
        "models",
        "pipelines",
        "services",
        "scripts",
    )
    files: list[Path] = []
    for dirname in runtime_dirs:
        files.extend((BACKEND_ROOT / dirname).rglob("*.py"))
    return [path for path in files if "__pycache__" not in path.parts]


def test_no_forbidden_or_hardcoded_inference_hosts_in_runtime_code() -> None:
    patterns = [
        re.compile(r"api\.anthropic\.com"),
        re.compile(r"api\.openai\.com"),
        re.compile(r"FIREWORKS_BASE_URL\s*=\s*['\"]https?://"),
        re.compile(r"base_url\s*=\s*['\"]https?://"),
    ]
    hits: list[str] = []
    for path in _runtime_python_files():
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern.search(text):
                hits.append(f"{path.relative_to(PROJECT_ROOT)} matched {pattern.pattern}")

    assert hits == []


def test_direct_llm_client_construction_stays_in_explicit_choke_points() -> None:
    allowed = {
        Path("backend/core/llm_factory.py"),
        Path("backend/api/routes/byok.py"),
    }
    direct_client_patterns = [
        re.compile(r"\banthropic\.Anthropic\s*\("),
        re.compile(r"\bopenai\.OpenAI\s*\("),
        re.compile(r"\bAsyncOpenAI\s*\("),
        re.compile(r"\bOpenAIProvider\s*\("),
        re.compile(r"\bAnthropicProvider\s*\("),
    ]

    hits: list[str] = []
    for path in _runtime_python_files():
        rel = path.relative_to(PROJECT_ROOT)
        text = path.read_text(encoding="utf-8")
        if rel in allowed:
            continue
        for pattern in direct_client_patterns:
            if pattern.search(text):
                hits.append(f"{rel} matched {pattern.pattern}")

    assert hits == []


def test_existing_ci_docker_builds_target_linux_amd64() -> None:
    workflow = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
    if not workflow.exists():
        return

    text = workflow.read_text(encoding="utf-8")
    docker_build_lines = [line.strip() for line in text.splitlines() if "docker build" in line]
    assert docker_build_lines
    assert all("--platform linux/amd64" in line for line in docker_build_lines)
