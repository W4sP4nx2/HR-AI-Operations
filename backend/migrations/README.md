# Production migrations

`0001_platform_foundations.sql` is the first Supabase/PostgreSQL migration for
the Phase 1 platform contract. Apply it with the Supabase CLI or a controlled
PostgreSQL migration runner before enabling production workers.

The application keeps its SQLite-compatible `metadata.create_all` path for
local development and tests only. Production startup must not use runtime DDL;
service-role workers may write job state, while user-facing requests operate
through tenant membership and RLS.
