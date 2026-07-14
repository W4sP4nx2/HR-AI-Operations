"""Application configuration.

Loads settings from environment variables / .env using pydantic-settings.
No secrets are ever hardcoded; everything comes from the environment.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central settings object for the Govern.ai backend.

    Attributes:
        llm_provider: LLM backend ("anthropic", "fireworks", or empty/mock).
        anthropic_api_key: API key for Anthropic Claude. Loaded from env.
        claude_model: Claude model identifier used for Anthropic calls.
        fireworks_api_key: API key for Fireworks. Loaded from env.
        fireworks_base_url: OpenAI-compatible Fireworks base URL. Loaded from env.
        amd_vllm_base_url: Self-hosted AMD vLLM OpenAI-compatible base URL.
        allowed_models: Comma-separated model allow-list injected by the harness.
        qdrant_url: URL of the running Qdrant vector database.
        qdrant_collection: Name of the Qdrant collection for HR policy chunks.
        database_url: SQLAlchemy-style URL for the SQLite database.
        embedding_model: HuggingFace sentence-transformers model name.
        environment: Deployment environment (development / production).
        cors_origins: Allowed CORS origins for the FastAPI app.
        chunk_size: Token chunk size for RAG ingestion.
        chunk_overlap: Token overlap between chunks.
        retrieval_top_k: Number of chunks retrieved per RAG query.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets / external services -------------------------------------
    llm_provider: str = "fireworks"
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    fireworks_api_key: str = ""
    fireworks_base_url: str = ""
    fireworks_control_base_url: str = ""
    fireworks_account_id: str = ""
    fireworks_max_retries: int = 4
    fireworks_session_affinity: bool = True
    fireworks_serving_mode: str = "serverless"
    fireworks_batch_timeout_seconds: float = 30.0
    fireworks_vision_model: str = ""
    fireworks_batch_model: str = ""
    fireworks_gemma_model: str = ""
    amd_vllm_api_key: str = ""
    amd_vllm_base_url: str = ""
    allowed_models: str = ""
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "hr_policies"
    database_url: str = "sqlite:///./hr_command_center.db"

    # --- Models ----------------------------------------------------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_provider: str = "local"
    fireworks_embedding_model: str = ""
    embedding_batch_size: int = 32
    embedding_device: str = "auto"
    vector_write_batch_size: int = 128
    enable_gpu_kernels: bool = False
    gpu_kernel_min_corpus: int = 10_000
    gpu_kernel_min_speedup: float = 1.5
    gpu_kernel_measured_speedup: float = 0.0

    # --- App -------------------------------------------------------------
    environment: str = "development"
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
    # Shared secret for inbound webhooks. Empty in dev = no verification;
    # set in production and require it via the X-Webhook-Secret header.
    webhook_secret: str = ""

    # --- Auth / RBAC -----------------------------------------------------
    # JWT signing secret. MUST be overridden in production.
    jwt_secret: str = "dev-insecure-change-me-in-production-0123456789"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24h
    # When True (dev), email/password registration is open and the FIRST user
    # becomes admin. When False (prod), only Google OAuth or seeded users.
    auth_open_registration: bool = True
    # When True, protected routes require a valid token. When False (default for
    # zero-secret demos), auth is advisory: identity is attached if present but
    # RBAC is not enforced, so the app stays fully usable without setting up auth.
    auth_enforce: bool = False
    # Google OAuth (optional). When both are set, Google sign-in is available.
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_base: str = "http://localhost:8000"
    frontend_base: str = "http://localhost:3000"
    # Optional first-run admin: if both set, an admin account is created on boot.
    admin_email: str = ""
    admin_password: str = ""

    # --- Demo resilience / cost ------------------------------------------
    # DEMO_MODE caches LLM/tool outputs and avoids external flakiness for live
    # demos. MOCK_LLM forces deterministic responses even if a key is present.
    demo_mode: bool = False
    mock_llm: bool = False
    # Number of recent policy answers to cache (cost + latency).
    policy_cache_size: int = 32
    # How long (seconds) a cached RAG answer stays fresh. 0 = no expiry.
    semantic_cache_ttl: int = 3600
    # Bound chat policy search so a cold embedder or unavailable vector backend
    # cannot leave the browser streaming forever.
    chat_policy_timeout_seconds: float = 15.0
    max_llm_input_tokens: int = 4000
    max_llm_output_tokens: int = 1000
    # 0 disables the circuit breaker. When positive and estimated spend crosses
    # the threshold, routing is forced to the economy model and cache TTL is
    # raised for the rest of the process.
    daily_inference_budget_usd: float = 0.0
    circuit_breaker_cache_ttl_seconds: int = 86_400

    # --- Cost / abuse controls -------------------------------------------
    # Per-IP request budget over a rolling window. 0 disables the limiter
    # (default for dev/tests); set in production to cap spend/abuse.
    rate_limit_requests: int = 0
    rate_limit_window_seconds: int = 3600
    # Reject uploads larger than this (PDF policies / resumes). DoS + cost guard.
    max_upload_size_mb: int = 25
    enable_resume_vlm: bool = False
    resume_vlm_max_pages: int = 50
    resume_concurrency_limit: int = 10

    # --- Safety / observability ------------------------------------------
    # Redact emails / phone / common IDs from text written to audit + chat + tools.
    redact_pii: bool = True
    # PII engine: "regex" (default, zero-dep) or "presidio" (NER: also names).
    pii_engine: str = "regex"
    # Policy answers below this confidence are flagged "needs human review".
    confidence_threshold: float = 0.7
    # Attrition risk at/above which a prediction is flagged for human review and
    # triggers the policy-grounded retention composition. Calibrated to the
    # attrition model's own output range (healthy ≈0.05 … severe ≈0.45) — a
    # separate knob from the RAG cosine floor above.
    attrition_review_threshold: float = 0.35

    # --- RAG tuning ------------------------------------------------------
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 5
    # Vector backend: "auto" (pgvector on Postgres, else Qdrant if set, else
    # degraded), "pgvector", "qdrant", or "none". ENABLE_RAG gates retrieval.
    enable_rag: bool = True
    vector_backend: str = "auto"
    # Guard the destructive self-heal: on a vector-dimension mismatch the
    # pgvector store would DROP + recreate policy_chunks, wiping live data. In
    # production that must be an explicit, operator-run re-index — not a silent
    # side effect of a boot. Default off: on mismatch we log loudly and degrade
    # (RAG returns no hits) instead of destroying retained embeddings.
    allow_destructive_reindex: bool = False

    # Master key for encrypting provider credentials saved by the Settings UI.
    # Production should inject a dedicated secret; the JWT secret is only the
    # local fallback so a fresh development install remains usable.
    ai_settings_encryption_key: str = ""

    @property
    def sqlite_path(self) -> str:
        """Return the bare filesystem path from a sqlite:/// URL."""
        return self.database_url.replace("sqlite:///", "")


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Using an lru_cache ensures the .env file is parsed only once per process.
    """
    return Settings()


settings = get_settings()
