-- Govern.ai Phase 1 platform foundations
-- Apply once, in order, before enabling production resume workers.

create extension if not exists vector;

create table if not exists tenants (
    id text primary key,
    name text not null,
    status text not null default 'active' check (status in ('active', 'suspended')),
    created_at timestamptz not null default now()
);

create table if not exists tenant_memberships (
    tenant_id text not null references tenants(id) on delete cascade,
    user_id text not null,
    role text not null check (role in ('viewer', 'manager', 'admin')),
    created_at timestamptz not null default now(),
    primary key (tenant_id, user_id)
);

create index if not exists idx_tenant_memberships_user
    on tenant_memberships (user_id, tenant_id);

create table if not exists resume_jobs (
    id text primary key,
    tenant_id text not null references tenants(id) on delete cascade,
    created_by text not null,
    idempotency_key text not null,
    state text not null check (state in (
        'queued', 'running', 'certified', 'needs_review', 'failed', 'cancelled', 'expired'
    )),
    filename text not null,
    source_object_key text not null,
    size_bytes bigint not null check (size_bytes between 1 and 26214400),
    pages_total integer check (pages_total between 1 and 50),
    pages_completed integer not null default 0 check (pages_completed >= 0),
    coverage double precision not null default 0 check (coverage between 0 and 1),
    result_json jsonb,
    error_code text,
    error_detail text,
    trace_id text not null,
    attempt integer not null default 0 check (attempt >= 0),
    version bigint not null default 1,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    started_at timestamptz,
    completed_at timestamptz,
    unique (tenant_id, idempotency_key)
);

create index if not exists idx_resume_jobs_tenant_state
    on resume_jobs (tenant_id, state, updated_at desc);

create table if not exists workflow_runs (
    id text primary key,
    tenant_id text not null references tenants(id) on delete cascade,
    workflow text not null,
    state text not null,
    actor_id text not null,
    trace_id text not null,
    policy_version text not null,
    guardrail_version text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists evidence_refs (
    id text primary key,
    tenant_id text not null references tenants(id) on delete cascade,
    run_id text not null references workflow_runs(id) on delete cascade,
    source_type text not null,
    source_ref text not null,
    content_hash text not null,
    excerpt text,
    created_at timestamptz not null default now()
);

create index if not exists idx_evidence_refs_run on evidence_refs (tenant_id, run_id);

-- Supabase's auth.uid() is the caller identity. service_role bypasses RLS for
-- workers/migrations; no browser request receives that role.
alter table tenants enable row level security;
alter table tenant_memberships enable row level security;
alter table resume_jobs enable row level security;
alter table workflow_runs enable row level security;
alter table evidence_refs enable row level security;

create policy tenant_memberships_self_read on tenant_memberships
    for select using (user_id = auth.uid()::text);

create policy tenants_member_read on tenants
    for select using (exists (
        select 1 from tenant_memberships m
        where m.tenant_id = tenants.id and m.user_id = auth.uid()::text
    ));

create policy resume_jobs_member_read on resume_jobs
    for select using (exists (
        select 1 from tenant_memberships m
        where m.tenant_id = resume_jobs.tenant_id and m.user_id = auth.uid()::text
    ));

create policy resume_jobs_manager_write on resume_jobs
    for all using (exists (
        select 1 from tenant_memberships m
        where m.tenant_id = resume_jobs.tenant_id
          and m.user_id = auth.uid()::text
          and m.role in ('manager', 'admin')
    )) with check (exists (
        select 1 from tenant_memberships m
        where m.tenant_id = resume_jobs.tenant_id
          and m.user_id = auth.uid()::text
          and m.role in ('manager', 'admin')
    ));

create policy workflow_runs_member_read on workflow_runs
    for select using (exists (
        select 1 from tenant_memberships m
        where m.tenant_id = workflow_runs.tenant_id and m.user_id = auth.uid()::text
    ));

create policy evidence_refs_member_read on evidence_refs
    for select using (exists (
        select 1 from tenant_memberships m
        where m.tenant_id = evidence_refs.tenant_id and m.user_id = auth.uid()::text
    ));
