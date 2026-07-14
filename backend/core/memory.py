"""Agent memory and persistence layer.

Provides a single async interface used across the system for:
  * the compliance audit log (every agent action),
  * HR case storage and status updates,
  * agent runtime state (status, last action, run counts),
  * durable agent task state for human-in-the-loop checkpoints.

Storage is **async SQLAlchemy Core** so the same code runs against SQLite for
local development and PostgreSQL in production — selected purely by
``DATABASE_URL``:

    sqlite:///./hr_command_center.db          → SQLite (aiosqlite)        [dev]
    postgresql://user:pass@host:5432/hrdb     → PostgreSQL (asyncpg)      [prod]

The public method surface (``log_audit``, ``create_case``, …) is unchanged, so
agents and routes are unaffected by the backend swap. SQLite connections are
tuned with WAL + busy-timeout; Postgres gets MVCC concurrency natively.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    event,
    func,
    insert,
    inspect,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings

# --------------------------------------------------------------------------- #
# Schema (SQLAlchemy Core — dialect-agnostic, works on SQLite and Postgres)
# --------------------------------------------------------------------------- #
metadata = MetaData()

audit_t = Table(
    "audit",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("agent_name", String(128), nullable=False),
    Column("action_type", String(128), nullable=False),
    Column("input", Text),
    Column("output", Text),
    Column("status", String(32), nullable=False),
    Column("timestamp", String(40), nullable=False),
    # The /audit endpoints sort by time and filter by agent; index both so reads
    # stay sub-linear as the audit log grows into the millions of rows.
    Index("idx_audit_timestamp", "timestamp"),
    Index("idx_audit_agent_ts", "agent_name", "timestamp"),
)

cases_t = Table(
    "cases",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("category", String(64)),
    Column("status", String(32), nullable=False),
    Column("assigned_agent", String(128)),
    Column("summary", Text),
    Column("detail", Text),
    # First-class AI recommendation, computed synchronously at triage time (the
    # POLICY auto-resolve path in TriageAgent.run). Nullable: non-POLICY cases
    # carry no recommendation. Advisory only — a human still verifies/closes.
    Column("ai_recommendation", Text, nullable=True),
    Column("ai_confidence", Float, nullable=True),
    # How the recommendation was produced (llm / grounded_excerpt / no_context /
    # llm_error) — so the UI never lets a deterministic excerpt pose as LLM reasoning.
    Column("ai_mode", String(32), nullable=True),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Index("idx_cases_category", "category"),
    Index("idx_cases_status", "status"),
    Index("idx_cases_created", "created_at"),
)

agents_t = Table(
    "agents",
    metadata,
    Column("name", String(128), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("last_action", Text),
    Column("last_run", String(40)),
    Column("total_runs", Integer, nullable=False, default=0),
)

agent_tasks_t = Table(
    "agent_tasks",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("agent_name", String(128), nullable=False),
    Column("step", String(128)),
    Column("status", String(32), nullable=False),
    Column("context", Text),
    Column("state", Text),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Index("idx_tasks_status", "status"),
)

# Append-only ledger of human feedback on agent suggestions (e.g. a manager
# accepting/rejecting/editing a retention option). Captured for human-facing
# "what's working" analytics — deliberately NOT fed back into the agents to steer
# future output (that would be an unauditable, bias-prone reward loop). There is
# no update/delete path: the table is immutable by construction.
agent_feedback_t = Table(
    "agent_feedback",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("case_id", String(64)),
    Column("suggestion_id", String(128)),
    Column("risk_driver", String(64)),
    Column("action_taken", String(16), nullable=False),  # accepted|rejected|edited
    Column("manager_notes", Text),  # PII-redacted before insert
    Column("decided_by_id", String(64)),  # non-PII actor id
    Column("created_at", String(40), nullable=False),
    Index("idx_feedback_driver", "risk_driver"),
)

# Tracks every policy document ingested into the vector store.
policies_t = Table(
    "policies",
    metadata,
    Column("doc_id", String(255), primary_key=True),
    Column("filename", String(255), nullable=False),
    Column("chunks", Integer, nullable=False, default=0),
    Column("char_count", Integer, nullable=False, default=0),
    Column("status", String(32), nullable=False, default="ingested"),
    Column("ingested_at", String(40), nullable=False),
    # Retained extracted text so a soft-deleted policy can be re-embedded (undo).
    Column("source_text", Text),
    Index("idx_policies_status", "status"),
)

# User accounts for authentication + RBAC.
users_t = Table(
    "users",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("email", String(255), nullable=False, unique=True),
    Column("name", String(255)),
    Column("role", String(32), nullable=False, default="viewer"),
    Column("password_hash", String(255)),  # null for OAuth-only accounts
    Column("provider", String(32), nullable=False, default="local"),  # local|google
    Column("avatar_url", Text),
    Column("created_at", String(40), nullable=False),
    Column("last_login", String(40)),
    Index("idx_users_email", "email"),
)

# Chat sessions group a conversation's messages (scoped to a user when authed).
chat_sessions_t = Table(
    "chat_sessions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("user_id", String(64)),  # null for anonymous/dev
    Column("title", Text),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Index("idx_chat_sessions_user", "user_id", "updated_at"),
)

chat_messages_t = Table(
    "chat_messages",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("session_id", String(64), nullable=False),
    Column("role", String(16), nullable=False),  # user|assistant
    Column("content", Text, nullable=False),
    Column("tool_calls", Text),  # JSON list
    Column("mode", String(16)),  # full|degraded|error
    Column("created_at", String(40), nullable=False),
    Index("idx_chat_messages_session", "session_id", "created_at"),
)

batch_jobs_t = Table(
    "batch_jobs",
    metadata,
    Column("job_id", String(128), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("provider_state", String(64), nullable=False),
    Column("processed_requests", Integer),
    Column("total_requests", Integer),
    Column("failed_requests", Integer),
    Column("output_dataset_id", String(128)),
    Column("updated_at", String(40), nullable=False),
    Index("idx_batch_jobs_status", "status", "updated_at"),
)

# Durable large-resume workflow state. The original document lives in private
# object storage; this table contains only the processing manifest and bounded
# result/error metadata needed by the API, workers, and command center.
resume_jobs_t = Table(
    "resume_jobs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant_id", String(128), nullable=False),
    Column("created_by", String(128), nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("state", String(32), nullable=False),
    Column("filename", String(255), nullable=False),
    Column("source_object_key", Text, nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("pages_total", Integer),
    Column("pages_completed", Integer, nullable=False, default=0),
    Column("coverage", Float, nullable=False, default=0.0),
    Column("result_json", Text),
    Column("error_code", String(64)),
    Column("error_detail", Text),
    Column("trace_id", String(128), nullable=False),
    Column("attempt", Integer, nullable=False, default=0),
    Column("version", Integer, nullable=False, default=1),
    Column("created_at", String(40), nullable=False),
    Column("updated_at", String(40), nullable=False),
    Column("started_at", String(40)),
    Column("completed_at", String(40)),
    Index("idx_resume_jobs_tenant_state", "tenant_id", "state", "updated_at"),
    Index("uq_resume_jobs_tenant_idempotency", "tenant_id", "idempotency_key", unique=True),
)

# Singleton operator configuration. Non-secret settings are stored as JSON;
# provider credentials are stored separately as encrypted ciphertext.
runtime_settings_t = Table(
    "runtime_settings",
    metadata,
    Column("scope", String(64), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("encrypted_api_keys", Text, nullable=False, default="{}"),
    Column("updated_at", String(40), nullable=False),
)


def _utcnow() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _async_url(database_url: str) -> str:
    """Translate a plain DB URL into its async-driver form.

    ``sqlite:///x`` → ``sqlite+aiosqlite:///x``; ``postgresql://`` (or the
    ``postgres://`` alias) → ``postgresql+asyncpg://``. A bare filesystem path is
    treated as a SQLite file. URLs that already name a driver pass through.
    """
    if "+" in database_url.split("://", 1)[0]:
        return database_url  # already has an explicit driver
    if database_url.startswith("sqlite:///"):
        return database_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if "://" not in database_url:
        return f"sqlite+aiosqlite:///{database_url}"
    return database_url


class Memory:
    """Async, SQLAlchemy-backed persistence used by agents and the API."""

    def __init__(self, database_url: str | None = None) -> None:
        """Create the async engine (lazily connected) for the configured store.

        Args:
            database_url: Optional override; defaults to ``settings.database_url``.
                Accepts a full URL or a bare SQLite file path.
        """
        url = _async_url(database_url or settings.database_url)
        self._is_sqlite = url.startswith("sqlite")
        engine_kwargs: dict[str, Any] = {"future": True}
        # SQLite: NullPool avoids reusing a connection across event loops (e.g.
        # multiple asyncio.run() calls in tests) and keeps WAL pragmas per-conn.
        # Postgres: the default async pool is correct (front it with PgBouncer
        # in production for thousands of coroutines → a bounded server pool).
        if self._is_sqlite:
            engine_kwargs["poolclass"] = NullPool
        self._engine: AsyncEngine = create_async_engine(url, **engine_kwargs)
        if self._is_sqlite:
            self._register_sqlite_pragmas(self._engine)
        self._schema_ready = False
        self._schema_lock = asyncio.Lock()

    @property
    def engine(self) -> AsyncEngine:
        """The shared async engine (reused by the pgvector store)."""
        return self._engine

    @property
    def is_postgres(self) -> bool:
        """True when the configured database is PostgreSQL."""
        return not self._is_sqlite

    @staticmethod
    def _register_sqlite_pragmas(engine: AsyncEngine) -> None:
        """Apply WAL + busy-timeout on each new SQLite connection.

        WAL lets readers run concurrently with a single writer; ``busy_timeout``
        makes contending writers wait-and-retry instead of failing with
        "database is locked"; ``synchronous=NORMAL`` is the safe, faster WAL mode.
        """

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn: Any, _record: Any) -> None:
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    async def _ensure_schema(self) -> None:
        """Create tables/indexes on first use (idempotent, run once)."""
        if self._schema_ready:
            return
        async with self._schema_lock:
            if self._schema_ready:
                return
            async with self._engine.begin() as conn:
                await conn.run_sync(metadata.create_all)
                # create_all never ALTERs an existing table, so columns added to
                # a Table after a DB already exists (e.g. cases.ai_recommendation)
                # are missing on upgrade. Additively backfill them — nullable
                # columns only, so existing rows stay valid and no data is moved
                # or dropped. Idempotent: a column already present is skipped.
                await conn.run_sync(self._backfill_columns)
            self._schema_ready = True

    @staticmethod
    def _backfill_columns(sync_conn: Any) -> None:
        """ADD COLUMN for any model column missing from the live table (additive)."""
        inspector = inspect(sync_conn)
        dialect = sync_conn.dialect
        for table in metadata.tables.values():
            if not inspector.has_table(table.name):
                continue
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=dialect)
                sync_conn.exec_driver_sql(
                    f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}"
                )

    # ------------------------------------------------------------------ #
    # Audit log
    # ------------------------------------------------------------------ #
    async def log_audit(
        self,
        agent_name: str,
        action_type: str,
        input_data: Any,
        output_data: Any,
        status: str = "success",
    ) -> dict[str, Any]:
        """Append an entry to the compliance audit log.

        Args:
            agent_name: Name of the agent performing the action.
            action_type: Short action identifier (e.g. ``"query"``).
            input_data: JSON-serialisable input summary.
            output_data: JSON-serialisable output summary.
            status: ``"success"``, ``"error"`` or ``"paused"``.

        Returns:
            The inserted audit record.
        """
        await self._ensure_schema()
        # Redact PII before anything is persisted to the audit trail.
        from core.safety import redact_obj

        record = {
            "id": str(uuid.uuid4()),
            "agent_name": agent_name,
            "action_type": action_type,
            "input": json.dumps(redact_obj(input_data), default=str)[:4000],
            "output": json.dumps(redact_obj(output_data), default=str)[:4000],
            "status": status,
            "timestamp": _utcnow(),
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(audit_t).values(**record))
        return record

    async def list_audit(self, agent: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        """Return audit rows ordered by most recent first."""
        await self._ensure_schema()
        stmt = select(audit_t)
        if agent:
            stmt = stmt.where(audit_t.c.agent_name == agent)
        stmt = stmt.order_by(audit_t.c.timestamp.desc()).limit(limit)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def list_audit_for_case(self, case_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return audit rows that reference a given case id.

        Agents record the case id inside the audit ``input``/``output`` JSON, so
        a substring match surfaces the activity trail for a single case
        (``LIKE`` works on both SQLite and Postgres).

        Args:
            case_id: The case identifier to search for.
            limit: Maximum rows to return.

        Returns:
            Matching audit rows, oldest first (chronological activity trail).
        """
        await self._ensure_schema()
        like = f"%{case_id}%"
        stmt = (
            select(audit_t)
            .where(audit_t.c.input.like(like) | audit_t.c.output.like(like))
            .order_by(audit_t.c.timestamp.asc())
            .limit(limit)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Metrics aggregations (audit log = single source of truth)
    #
    # These are SQL ``COUNT(*) … GROUP BY`` rollups, not Python loops, so they
    # stay correct as the log grows past any in-memory page size. The /metrics
    # endpoint and Analytics panel are pure *queries* over these — no agent ever
    # computes a metric itself (Stripe-style: immutable log → derived metrics).
    # ------------------------------------------------------------------ #
    async def count_audit(self) -> int:
        """Total number of recorded agent actions (audit rows)."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            return int(
                (await conn.execute(select(func.count()).select_from(audit_t))).scalar() or 0
            )

    async def audit_counts_by_agent(self) -> list[dict[str, Any]]:
        """Action count per agent, busiest first (drives the activity chart)."""
        await self._ensure_schema()
        stmt = (
            select(audit_t.c.agent_name, func.count().label("count"))
            .group_by(audit_t.c.agent_name)
            .order_by(func.count().desc())
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [{"agent": r[0], "count": int(r[1])} for r in rows]

    async def audit_counts_by_action(self) -> dict[str, int]:
        """Count of audit rows per ``action_type`` (e.g. triage, resume_screen)."""
        await self._ensure_schema()
        stmt = select(audit_t.c.action_type, func.count()).group_by(audit_t.c.action_type)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return {r[0]: int(r[1]) for r in rows}

    async def case_counts_by_status(self) -> dict[str, int]:
        """Count of cases per status (open/escalated/resolved) — the active counter."""
        await self._ensure_schema()
        stmt = select(cases_t.c.status, func.count()).group_by(cases_t.c.status)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return {r[0]: int(r[1]) for r in rows}

    async def case_counts_by_category(self) -> list[dict[str, Any]]:
        """Count of cases per triage category (the triage distribution)."""
        await self._ensure_schema()
        stmt = (
            select(cases_t.c.category, func.count().label("count"))
            .group_by(cases_t.c.category)
            .order_by(func.count().desc())
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return [{"category": r[0], "count": int(r[1])} for r in rows]

    async def count_cases_resolved_since(self, iso_ts: str) -> int:
        """Number of cases resolved with ``created_at >= iso_ts`` (today's KPI)."""
        await self._ensure_schema()
        stmt = (
            select(func.count())
            .select_from(cases_t)
            .where(cases_t.c.status == "resolved", cases_t.c.created_at >= iso_ts)
        )
        async with self._engine.connect() as conn:
            return int((await conn.execute(stmt)).scalar() or 0)

    async def list_approval_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return resolved human-in-the-loop decisions from the audit log.

        Approve/reject are written as ``human_approved`` / ``human_rejected``
        audit rows (the single source of truth), so the Approvals page can show
        a decision history just by querying — no separate table to keep in sync.
        """
        await self._ensure_schema()
        stmt = (
            select(audit_t)
            .where(audit_t.c.action_type.in_(["human_approved", "human_rejected"]))
            .order_by(audit_t.c.timestamp.desc())
            .limit(limit)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        history: list[dict[str, Any]] = []
        for r in rows:
            try:
                inp = json.loads(r["input"]) if r["input"] else {}
            except (ValueError, TypeError):
                inp = {}
            history.append(
                {
                    "id": r["id"],
                    "agent_name": r["agent_name"],
                    "decision": (
                        "approved" if r["action_type"] == "human_approved" else "rejected"
                    ),
                    "step": inp.get("step"),
                    "reason": inp.get("reason") or "",
                    "decided_by_id": inp.get("decided_by_id"),
                    "role": inp.get("role"),
                    "timestamp": r["timestamp"],
                }
            )
        return history

    async def find_case_by_detail(self, detail: str) -> dict[str, Any] | None:
        """Return a case whose ``detail`` exactly matches (seed de-duplication)."""
        await self._ensure_schema()
        stmt = select(cases_t).where(cases_t.c.detail == detail).limit(1)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    # Cases
    # ------------------------------------------------------------------ #
    async def create_case(
        self,
        category: str,
        summary: str,
        detail: str = "",
        assigned_agent: str = "triage_agent",
        status: str = "open",
        ai_recommendation: str | None = None,
        ai_confidence: float | None = None,
        ai_mode: str | None = None,
    ) -> dict[str, Any]:
        """Create an HR case and return the stored record.

        ``ai_recommendation`` / ``ai_confidence`` / ``ai_mode`` are populated by
        the caller when a recommendation was computed synchronously (the POLICY
        auto-resolve path); they stay ``None`` otherwise.
        """
        await self._ensure_schema()
        now = _utcnow()
        record = {
            "id": f"CASE-{uuid.uuid4().hex[:8].upper()}",
            "category": category,
            "status": status,
            "assigned_agent": assigned_agent,
            "summary": summary,
            "detail": detail,
            "ai_recommendation": ai_recommendation,
            "ai_confidence": ai_confidence,
            "ai_mode": ai_mode,
            "created_at": now,
            "updated_at": now,
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(cases_t).values(**record))
        return record

    async def update_case(self, case_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update a case's fields and return the refreshed record."""
        await self._ensure_schema()
        if not fields:
            return await self.get_case(case_id)
        fields["updated_at"] = _utcnow()
        async with self._engine.begin() as conn:
            await conn.execute(update(cases_t).where(cases_t.c.id == case_id).values(**fields))
        return await self.get_case(case_id)

    async def get_case(self, case_id: str) -> dict[str, Any] | None:
        """Fetch a single case by id."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (await conn.execute(select(cases_t).where(cases_t.c.id == case_id)))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def list_cases(
        self,
        category: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """List HR cases with optional category/status filters."""
        await self._ensure_schema()
        stmt = select(cases_t)
        if category:
            stmt = stmt.where(cases_t.c.category == category)
        if status:
            stmt = stmt.where(cases_t.c.status == status)
        stmt = stmt.order_by(cases_t.c.created_at.desc()).limit(limit)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def list_cases_page(
        self,
        category: str | None = None,
        status: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Cursor-page HR cases for large datasets without offset scans."""
        await self._ensure_schema()
        page_size = max(1, min(limit, 200))
        stmt = select(cases_t)
        if category:
            stmt = stmt.where(cases_t.c.category == category)
        if status:
            stmt = stmt.where(cases_t.c.status == status)
        if cursor:
            # The operator queue is newest-first. Keep the cursor opaque to the
            # frontend while using a stable timestamp + id tie-breaker so a
            # freshly-created case is visible on the first page.
            cursor_created_at, separator, cursor_id = cursor.partition("|")
            if separator:
                stmt = stmt.where(
                    or_(
                        cases_t.c.created_at < cursor_created_at,
                        and_(
                            cases_t.c.created_at == cursor_created_at,
                            cases_t.c.id < cursor_id,
                        ),
                    )
                )
            else:
                # Accept legacy id-only cursors from older clients.
                stmt = stmt.where(cases_t.c.id < cursor)
        stmt = stmt.order_by(cases_t.c.created_at.desc(), cases_t.c.id.desc()).limit(page_size + 1)
        async with self._engine.connect() as conn:
            rows = [dict(row) for row in (await conn.execute(stmt)).mappings().all()]
        next_cursor = (
            f"{rows[page_size - 1]['created_at']}|{rows[page_size - 1]['id']}"
            if len(rows) > page_size
            else None
        )
        return {
            "items": rows[:page_size],
            "next_cursor": next_cursor,
            "limit": page_size,
        }

    # ------------------------------------------------------------------ #
    # Agent runtime state
    # ------------------------------------------------------------------ #
    async def upsert_agent(
        self,
        name: str,
        status: str | None = None,
        last_action: str | None = None,
        increment_runs: bool = False,
    ) -> dict[str, Any]:
        """Create or update an agent runtime record."""
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            existing = (
                (await conn.execute(select(agents_t).where(agents_t.c.name == name)))
                .mappings()
                .first()
            )
            if existing is None:
                await conn.execute(
                    insert(agents_t).values(
                        name=name,
                        status=status or "idle",
                        last_action=last_action,
                        last_run=_utcnow(),
                        total_runs=0,
                    )
                )
            else:
                runs = existing["total_runs"] + (1 if increment_runs else 0)
                await conn.execute(
                    update(agents_t)
                    .where(agents_t.c.name == name)
                    .values(
                        status=status or existing["status"],
                        last_action=last_action or existing["last_action"],
                        last_run=_utcnow(),
                        total_runs=runs,
                    )
                )
            row = (
                (await conn.execute(select(agents_t).where(agents_t.c.name == name)))
                .mappings()
                .first()
            )
        return dict(row)

    async def list_agents(self) -> list[dict[str, Any]]:
        """Return all agent runtime records."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            rows = (await conn.execute(select(agents_t).order_by(agents_t.c.name))).mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Agent tasks (human-in-the-loop checkpoints)
    # ------------------------------------------------------------------ #
    async def create_agent_task(
        self, agent_name: str, step: str, context: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Persist a paused agent task for human review."""
        await self._ensure_schema()
        now = _utcnow()
        record = {
            "id": f"TASK-{uuid.uuid4().hex[:8].upper()}",
            "agent_name": agent_name,
            "step": step,
            "status": "awaiting_approval",
            "context": context,
            "state": json.dumps(state, default=str),
            "created_at": now,
            "updated_at": now,
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(agent_tasks_t).values(**record))
        return record

    async def list_pending_tasks(self) -> list[dict[str, Any]]:
        """Return all agent tasks awaiting human approval."""
        await self._ensure_schema()
        stmt = (
            select(agent_tasks_t)
            .where(agent_tasks_t.c.status == "awaiting_approval")
            .order_by(agent_tasks_t.c.created_at.desc())
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def resolve_agent_task(
        self, task_id: str, status: str, reason: str = ""
    ) -> dict[str, Any] | None:
        """Atomically decide a paused agent task; return the row, or None if it
        was already decided.

        The ``WHERE status = 'awaiting_approval'`` clause makes this a
        compare-and-set: only the first of any concurrent approve/reject requests
        transitions the task (``rowcount == 1``); a racing second request updates
        nothing (``rowcount == 0``) and gets ``None`` back. This is what stops a
        double-click — or two parallel requests — from resuming the workflow (and
        re-running its side-effects) twice, without any new dependency.
        """
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            # ``.concat`` maps to the ``||`` operator on both SQLite and Postgres.
            result = await conn.execute(
                update(agent_tasks_t)
                .where(
                    agent_tasks_t.c.id == task_id,
                    agent_tasks_t.c.status == "awaiting_approval",
                )
                .values(
                    status=status,
                    context=agent_tasks_t.c.context.concat(" | ").concat(reason or status),
                    updated_at=_utcnow(),
                )
            )
            if result.rowcount == 0:
                return None  # task missing or already decided — caller must not resume
            row = (
                (await conn.execute(select(agent_tasks_t).where(agent_tasks_t.c.id == task_id)))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    # Agent feedback ledger (append-only; human "what's working" signal)
    # ------------------------------------------------------------------ #
    async def record_feedback(
        self,
        *,
        case_id: str,
        suggestion_id: str,
        risk_driver: str,
        action_taken: str,
        manager_notes: str = "",
        decided_by_id: str = "unknown",
    ) -> dict[str, Any]:
        """Append one feedback row. Insert-only — there is no update/delete path."""
        await self._ensure_schema()
        from core.safety import redact_pii

        record = {
            "id": str(uuid.uuid4()),
            "case_id": case_id,
            "suggestion_id": suggestion_id,
            "risk_driver": risk_driver,
            "action_taken": action_taken,
            "manager_notes": redact_pii(manager_notes or "")[:2000],
            "decided_by_id": decided_by_id,
            "created_at": _utcnow(),
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(agent_feedback_t).values(**record))
        return record

    async def feedback_stats(self) -> list[dict[str, Any]]:
        """Per-driver acceptance aggregates, derived by ``GROUP BY`` (newest-heavy first).

        Returns one row per ``risk_driver`` with accepted/rejected/edited counts,
        the total, and an exact acceptance_rate — the human-facing "what's
        working" signal. Pure query: no agent state, no steering.
        """
        await self._ensure_schema()
        stmt = select(
            agent_feedback_t.c.risk_driver,
            agent_feedback_t.c.action_taken,
            func.count().label("n"),
        ).group_by(agent_feedback_t.c.risk_driver, agent_feedback_t.c.action_taken)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()

        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            d = agg.setdefault(
                r["risk_driver"],
                {
                    "risk_driver": r["risk_driver"],
                    "accepted": 0,
                    "rejected": 0,
                    "edited": 0,
                },
            )
            if r["action_taken"] in ("accepted", "rejected", "edited"):
                d[r["action_taken"]] = int(r["n"])
        out: list[dict[str, Any]] = []
        for d in agg.values():
            total = d["accepted"] + d["rejected"] + d["edited"]
            d["total"] = total
            # Exact ratio (no lossy intermediate rounding); 4 dp is display-safe.
            d["acceptance_rate"] = round(d["accepted"] / total, 4) if total else 0.0
            out.append(d)
        out.sort(key=lambda d: d["total"], reverse=True)
        return out

    # ------------------------------------------------------------------ #
    # Fireworks Batch job ledger (metadata only; no resume/provider output)
    # ------------------------------------------------------------------ #
    async def upsert_batch_job(
        self,
        *,
        job_id: str,
        status: str,
        provider_state: str,
        processed_requests: int | None = None,
        total_requests: int | None = None,
        failed_requests: int | None = None,
        output_dataset_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist normalized Batch progress without candidate content."""
        await self._ensure_schema()
        record = {
            "job_id": job_id,
            "status": status,
            "provider_state": provider_state,
            "processed_requests": processed_requests,
            "total_requests": total_requests,
            "failed_requests": failed_requests,
            "output_dataset_id": output_dataset_id,
            "updated_at": _utcnow(),
        }
        async with self._engine.begin() as conn:
            exists = (
                await conn.execute(
                    select(batch_jobs_t.c.job_id).where(batch_jobs_t.c.job_id == job_id)
                )
            ).first()
            if exists:
                await conn.execute(
                    update(batch_jobs_t)
                    .where(batch_jobs_t.c.job_id == job_id)
                    .values(**{key: value for key, value in record.items() if key != "job_id"})
                )
            else:
                await conn.execute(insert(batch_jobs_t).values(**record))
        return record

    async def get_batch_job(self, job_id: str) -> dict[str, Any] | None:
        """Return one locally reconciled Batch job."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (await conn.execute(select(batch_jobs_t).where(batch_jobs_t.c.job_id == job_id)))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    # ------------------------------------------------------------------ #
    # Durable large-resume jobs
    # ------------------------------------------------------------------ #
    async def create_resume_job(
        self,
        *,
        tenant_id: str,
        created_by: str,
        idempotency_key: str,
        filename: str,
        source_object_key: str,
        size_bytes: int,
        pages_total: int | None,
        trace_id: str,
    ) -> tuple[dict[str, Any], bool]:
        """Create a queued resume job, returning ``(job, deduplicated)``."""
        await self._ensure_schema()
        existing = await self.get_resume_job_by_idempotency(tenant_id, idempotency_key)
        if existing:
            return existing, True
        now = _utcnow()
        record = {
            "id": f"RES-{uuid.uuid4().hex[:12].upper()}",
            "tenant_id": tenant_id,
            "created_by": created_by,
            "idempotency_key": idempotency_key,
            "state": "queued",
            "filename": filename[:255],
            "source_object_key": source_object_key,
            "size_bytes": size_bytes,
            "pages_total": pages_total,
            "pages_completed": 0,
            "coverage": 0.0,
            "result_json": None,
            "error_code": None,
            "error_detail": None,
            "trace_id": trace_id,
            "attempt": 0,
            "version": 1,
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "completed_at": None,
        }
        try:
            async with self._engine.begin() as conn:
                await conn.execute(insert(resume_jobs_t).values(**record))
        except IntegrityError:
            # Two retries can race on the unique tenant/idempotency key. The
            # winner is the authoritative job; callers must not duplicate work.
            existing = await self.get_resume_job_by_idempotency(tenant_id, idempotency_key)
            if existing:
                return existing, True
            raise
        return record, False

    async def get_resume_job_by_idempotency(
        self, tenant_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        """Find a resume job by tenant-scoped idempotency key."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        select(resume_jobs_t).where(
                            resume_jobs_t.c.tenant_id == tenant_id,
                            resume_jobs_t.c.idempotency_key == idempotency_key,
                        )
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def get_resume_job(self, job_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        """Return one resume job, optionally constrained to a tenant."""
        await self._ensure_schema()
        stmt = select(resume_jobs_t).where(resume_jobs_t.c.id == job_id)
        if tenant_id:
            stmt = stmt.where(resume_jobs_t.c.tenant_id == tenant_id)
        async with self._engine.connect() as conn:
            row = (await conn.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def list_resume_jobs(
        self, tenant_id: str, states: tuple[str, ...] = ("queued", "running")
    ) -> list[dict[str, Any]]:
        """Return tenant-scoped jobs in the requested states, newest first."""
        await self._ensure_schema()
        stmt = (
            select(resume_jobs_t)
            .where(resume_jobs_t.c.tenant_id == tenant_id, resume_jobs_t.c.state.in_(states))
            .order_by(resume_jobs_t.c.updated_at.desc())
            .limit(200)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(row) for row in rows]

    async def transition_resume_job(
        self,
        job_id: str,
        tenant_id: str,
        *,
        from_states: tuple[str, ...],
        state: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        """CAS transition for cancellation/retry/worker state changes."""
        await self._ensure_schema()
        fields = {**fields, "state": state, "updated_at": _utcnow()}
        fields.setdefault("version", resume_jobs_t.c.version + 1)
        async with self._engine.begin() as conn:
            result = await conn.execute(
                update(resume_jobs_t)
                .where(
                    resume_jobs_t.c.id == job_id,
                    resume_jobs_t.c.tenant_id == tenant_id,
                    resume_jobs_t.c.state.in_(from_states),
                )
                .values(**fields)
            )
            if result.rowcount == 0:
                return None
        return await self.get_resume_job(job_id, tenant_id)

    # ------------------------------------------------------------------ #
    # Runtime AI settings
    # ------------------------------------------------------------------ #
    async def get_runtime_settings(self, scope: str = "global") -> dict[str, Any] | None:
        """Return persisted AI settings for a scope, including ciphertext only."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        select(runtime_settings_t).where(runtime_settings_t.c.scope == scope)
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def save_runtime_settings(
        self,
        payload: dict[str, Any],
        encrypted_api_keys: str,
        scope: str = "global",
    ) -> dict[str, Any]:
        """Upsert the encrypted operator settings record and return its row."""
        await self._ensure_schema()
        record = {
            "scope": scope,
            "payload": json.dumps(payload, sort_keys=True, default=str),
            "encrypted_api_keys": encrypted_api_keys,
            "updated_at": _utcnow(),
        }
        async with self._engine.begin() as conn:
            existing = (
                await conn.execute(
                    select(runtime_settings_t.c.scope).where(runtime_settings_t.c.scope == scope)
                )
            ).first()
            if existing:
                await conn.execute(
                    update(runtime_settings_t)
                    .where(runtime_settings_t.c.scope == scope)
                    .values(**{key: value for key, value in record.items() if key != "scope"})
                )
            else:
                await conn.execute(insert(runtime_settings_t).values(**record))
        return record

    # ------------------------------------------------------------------ #
    # Policy registry (tracks documents ingested into the vector store)
    # ------------------------------------------------------------------ #
    async def upsert_policy(
        self,
        doc_id: str,
        filename: str,
        chunks: int,
        char_count: int,
        status: str = "ingested",
        source_text: str | None = None,
    ) -> dict[str, Any]:
        """Record or update a policy document in the registry.

        ``source_text`` retains the extracted document text so a soft-deleted
        policy can be re-embedded (the undo path).
        """
        await self._ensure_schema()
        record = {
            "doc_id": doc_id,
            "filename": filename,
            "chunks": chunks,
            "char_count": char_count,
            "status": status,
            "ingested_at": _utcnow(),
            "source_text": (source_text or "")[:200000],
        }
        async with self._engine.begin() as conn:
            existing = (
                await conn.execute(select(policies_t).where(policies_t.c.doc_id == doc_id))
            ).first()
            if existing:
                await conn.execute(
                    update(policies_t).where(policies_t.c.doc_id == doc_id).values(**record)
                )
            else:
                await conn.execute(insert(policies_t).values(**record))
        return record

    async def get_policy(self, doc_id: str) -> dict[str, Any] | None:
        """Fetch a single policy registry row (incl. retained source_text)."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (await conn.execute(select(policies_t).where(policies_t.c.doc_id == doc_id)))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def list_policies(self, include_deleted: bool = False) -> list[dict[str, Any]]:
        """Return policy documents (newest first); soft-deleted ones hidden by default."""
        await self._ensure_schema()
        stmt = select(policies_t).order_by(policies_t.c.ingested_at.desc())
        if not include_deleted:
            stmt = stmt.where(policies_t.c.status != "deleted")
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def set_policy_status(self, doc_id: str, status: str) -> dict[str, Any] | None:
        """Soft-delete / restore by updating only the status (keeps source_text)."""
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            await conn.execute(
                update(policies_t).where(policies_t.c.doc_id == doc_id).values(status=status)
            )
        return await self.get_policy(doc_id)

    async def delete_policy(self, doc_id: str) -> bool:
        """Hard-delete a policy registry row (used by the scheduled purge / admin)."""
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            result = await conn.execute(policies_t.delete().where(policies_t.c.doc_id == doc_id))
        return result.rowcount > 0

    # ------------------------------------------------------------------ #
    # Users (auth + RBAC)
    # ------------------------------------------------------------------ #
    async def create_user(
        self,
        email: str,
        name: str = "",
        role: str = "viewer",
        password_hash: str | None = None,
        provider: str = "local",
        avatar_url: str | None = None,
    ) -> dict[str, Any]:
        """Create a user account and return the stored record."""
        await self._ensure_schema()
        record = {
            "id": f"USR-{uuid.uuid4().hex[:12]}",
            "email": email.lower().strip(),
            "name": name or email.split("@")[0],
            "role": role,
            "password_hash": password_hash,
            "provider": provider,
            "avatar_url": avatar_url,
            "created_at": _utcnow(),
            "last_login": None,
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(users_t).values(**record))
        return record

    async def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Fetch a user by email (case-insensitive)."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        select(users_t).where(users_t.c.email == email.lower().strip())
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        """Fetch a user by id."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (await conn.execute(select(users_t).where(users_t.c.id == user_id)))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def list_users(self) -> list[dict[str, Any]]:
        """Return all users (admin data control)."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            rows = (
                (await conn.execute(select(users_t).order_by(users_t.c.created_at)))
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    async def update_user(self, user_id: str, **fields: Any) -> dict[str, Any] | None:
        """Update mutable user fields (role, name, last_login, avatar)."""
        await self._ensure_schema()
        if not fields:
            return await self.get_user(user_id)
        async with self._engine.begin() as conn:
            await conn.execute(update(users_t).where(users_t.c.id == user_id).values(**fields))
        return await self.get_user(user_id)

    async def count_users(self) -> int:
        """Return the total number of users (used to bootstrap the first admin)."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            rows = (await conn.execute(select(users_t.c.id))).all()
        return len(rows)

    # ------------------------------------------------------------------ #
    # Chat history (sessions + messages, with data controls)
    # ------------------------------------------------------------------ #
    async def create_chat_session(
        self, user_id: str | None = None, title: str = "New chat"
    ) -> dict[str, Any]:
        """Create a chat session and return it."""
        await self._ensure_schema()
        now = _utcnow()
        record = {
            "id": f"SES-{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "title": title[:120],
            "created_at": now,
            "updated_at": now,
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(chat_sessions_t).values(**record))
        return record

    async def add_chat_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tool_calls: Any = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Append a message to a chat session and bump the session timestamp.

        Chat content is PII-sanitized before storage (log sanitization), so the
        persisted transcript never contains raw employee identifiers.
        """
        await self._ensure_schema()
        from core.safety import redact_pii

        now = _utcnow()
        record = {
            "id": f"MSG-{uuid.uuid4().hex[:12]}",
            "session_id": session_id,
            "role": role,
            "content": redact_pii(content),
            "tool_calls": json.dumps(tool_calls, default=str) if tool_calls else None,
            "mode": mode,
            "created_at": now,
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(chat_messages_t).values(**record))
            await conn.execute(
                update(chat_sessions_t)
                .where(chat_sessions_t.c.id == session_id)
                .values(updated_at=now)
            )
        return record

    async def list_chat_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """List chat sessions, optionally scoped to a user, newest first."""
        await self._ensure_schema()
        stmt = select(chat_sessions_t)
        if user_id is not None:
            stmt = stmt.where(chat_sessions_t.c.user_id == user_id)
        stmt = stmt.order_by(chat_sessions_t.c.updated_at.desc()).limit(100)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def get_chat_session(self, session_id: str) -> dict[str, Any] | None:
        """Return chat-session ownership metadata without loading its messages."""
        await self._ensure_schema()
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        select(chat_sessions_t).where(chat_sessions_t.c.id == session_id)
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def get_chat_messages(self, session_id: str) -> list[dict[str, Any]]:
        """Return all messages in a session in chronological order."""
        await self._ensure_schema()
        stmt = (
            select(chat_messages_t)
            .where(chat_messages_t.c.session_id == session_id)
            .order_by(chat_messages_t.c.created_at.asc())
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def delete_chat_session(self, session_id: str) -> bool:
        """Delete a chat session and all its messages (data control)."""
        await self._ensure_schema()
        async with self._engine.begin() as conn:
            await conn.execute(
                chat_messages_t.delete().where(chat_messages_t.c.session_id == session_id)
            )
            result = await conn.execute(
                chat_sessions_t.delete().where(chat_sessions_t.c.id == session_id)
            )
        return result.rowcount > 0


# Module-level singleton shared across the app.
memory = Memory()
