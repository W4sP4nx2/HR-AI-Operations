"""Static contract checks for the documented zero-spend local preview."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "local_preview.sh"


def test_local_preview_seeds_deterministic_vectors_before_startup() -> None:
    """The one-command preview must not start with an empty policy index."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "python3 -m scripts.seed_data" in source
    assert source.count("EMBEDDING_PROVIDER=hashing") >= 2
    assert 'BACKEND_PORT="${BACKEND_PORT:-8010}"' in source
    assert 'FRONTEND_PORT="${FRONTEND_PORT:-3001}"' in source
