"""Pytest session setup — isolate the test database from the dev/demo DB.

Without this, the suite uses the default ``DATABASE_URL`` (the demo's
``hr_command_center.db``), so running ``pytest`` while a demo is up would flatten
or mutate its seeded state mid-presentation. We point the whole session at a
throwaway temp SQLite file **before any app module imports**, so the
``core.memory`` singleton (created at import from ``settings.database_url``) binds
to the isolated DB. Tests that rebind ``memory`` to their own temp DBs still work.
"""

from __future__ import annotations

import os
import tempfile

# Must run before `core.config`/`core.memory` are imported by any test module.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="hr_test_db_")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_TEST_DB_DIR, 'test_hr_ops.db')}"
# Keep tests deterministic and key-free regardless of the developer's shell.
os.environ.setdefault("MOCK_LLM", "true")
os.environ.setdefault("LLM_PROVIDER", "anthropic")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("FIREWORKS_API_KEY", None)
os.environ.pop("FIREWORKS_BASE_URL", None)
os.environ.pop("ALLOWED_MODELS", None)
