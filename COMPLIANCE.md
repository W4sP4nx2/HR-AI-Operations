# Compliance & Security Evidence

What an auditor actually asks for, and where this system provides it. Status is
honest: **✅ enforced in code**, **🟡 partial / configurable**, **⏭ roadmap /
process** (not code you can ship). HR + AI are regulated — over-claiming is worse
than a gap, so gaps are labelled.

> Scope note: this is an **open-source reference implementation**. It gives you the
> technical controls and the evidence hooks; legal sign-off (DPIA, SCCs, vendor
> DPAs) is your organisation's process, not a library.

---

## 1. Auditor evidence package

| Evidence | Where it comes from | Status |
|----------|---------------------|--------|
| **Data Flow Diagram** (PII enters → flows → stores → exits, incl. LLM) | See §2 below | ✅ |
| **Audit Log Export** (user/action/timestamp/outcome/role) | `GET /audit/export` (CSV); decisions carry `decided_by_id` + `role` | ✅ |
| **RBAC Policy Doc** (roles → permissions + `AUTH_ENFORCE=true`) | §4 matrix; `core/security.py`; [SECURITY.md](./SECURITY.md) | ✅ |
| **Bias Test Report** (resume disparity, methodology, CI gate) | `tests/test_compliance.py` (name-blind identical scores) + §3 | ✅ |
| **Model Cards** (data source, accuracy, limits, human oversight) | [MODEL_CARDS.md](./MODEL_CARDS.md) | ✅ |
| **Retention/Deletion Proof** (auto-anonymise after N days) | PII redaction at write; chat/policy delete endpoints | 🟡 (manual delete; scheduled purge = roadmap) |
| **DPA / Vendor Agreements** (Anthropic/cloud) | Procurement | ⏭ process |
| **DPIA** (automated decision-making) | Legal | ⏭ process |
| **Incident Response Runbook** | [SECURITY.md](./SECURITY.md) disclosure + ops | 🟡 (disclosure documented; full runbook = process) |

---

## 2. Data flow & PII handling

```
Employee ─▶ Chat / Triage / Upload ─▶ Intake (PII present)
   │                                      │
   │                                      ├─▶ Agent (RAG / score / classify)
   │                                      │       │
   │                                      │       └─▶ LLM API (only if key set;
   │                                      │            MOCK_LLM/DEMO_MODE = no call)
   │                                      ▼
   │                          Audit write ──[PII REDACTED]──▶ DB (SQLite/Postgres)
   │                                      ▼
   └────────────── grounded answer ◀──────┘
```

- **PII is redacted before write** (emails/phones/SSNs/cards/IPs) — `core/safety.py`.
  Enforced in **both** `memory.log_audit` (audit rows) **and** `memory.add_chat_message`
  (chat transcript). Tested: `test_security.test_pii_not_at_rest_in_db`.
- **Engine:** `regex` by default (zero-dep); `PII_ENGINE=presidio` adds NER (names,
  locations) when `presidio-analyzer` is installed, with automatic regex fallback.
- **LLM calls happen only when explicitly enabled.** `MOCK_LLM=true` / `DEMO_MODE=true`
  guarantee **no external call** (no data leaves the instance).
- **No PII in client bundle / no keys in frontend** — keys are backend-only.
  Tested: `test_security.test_no_api_key_in_frontend_source`.

### Audit log schema

Every agent action and human decision is one immutable row (`audit` table):

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid | primary key |
| `agent_name` | str | the acting agent (or `chat_agent`) |
| `action_type` | str | e.g. `triage`, `policy_query`, `human_approved`, `human_rejected`, `prompt_injection_blocked` |
| `input` | json (text) | **PII-redacted**; decisions include `decided_by` (redacted), `decided_by_id` (stable actor id), `role`, `reason` |
| `output` | json (text) | **PII-redacted**; decisions include `decision`, `final_state` |
| `status` | str | `success` / `error` / `rejected` / `blocked` |
| `timestamp` | iso-8601 | UTC |

Structured **event** payloads (tool-call telemetry) follow
`{step, tool, input, output, fallback, confidence, prompt_version, timestamp}`
(`core.safety.audit_event`). Export: `GET /audit/export` → CSV
(`timestamp, agent_name, action_type, input, output, status`). The "who/what/when/why"
of any decision is reconstructable from `decided_by_id` + `role` + `reason` + `timestamp`.

### Retention policy

| Data | Where | Default | Control |
|------|-------|---------|---------|
| Audit log | `audit` (Postgres/SQLite) | retained (immutable) | partition by month + archive to object storage (SCALING.md); set a window with compliance |
| Chat transcripts | `chat_messages` | retained, **PII-redacted at write** | `DELETE /chat/sessions/{id}` (user/admin) |
| HR cases | `cases` | retained | per-record; org policy |
| Policies | `policies` + Qdrant | until removed | `DELETE /policies/{id}` |
| Onboarding state | `agent_tasks` | until resolved | resolved on approve/reject |

- **Right to erasure (GDPR Art.17 / CCPA):** chat sessions and policies are deletable
  today; PII is redacted at write so transcripts hold no raw identifiers. **Scheduled
  auto-purge** after a configurable window (e.g. EEOC 1yr / 3yr, GDPR Art.5(1)(e)) is
  the documented next step — see §6 status.
- **No PII at rest:** verified by `test_security.test_pii_not_at_rest_in_db`.

### Bias test methodology

- **Approach:** demographic blinding (`core.guardrails.blind_demographics`) removes
  name headers, age/graduation year, and **drops any line** mentioning a protected
  attribute (pregnancy/maternity/disability/veteran/marital status) **before scoring**.
- **Empirical gate — disparity ratio:** identical resumes that differ only by a
  demographically-coded name (Bertrand & Mullainathan name set: white/black ×
  male/female) are scored; we compute
  `disparity_ratio = max(score) / min(score)` and require **< 1.1** (a four-fifths-rule
  -inspired tolerance applied to scores). A blind scorer yields **1.0**.
- **Where:** `backend/tests/compliance/test_bias.py`, run as the **CI "Compliance
  gate" job** on every push (blocks merge). Also covers: age/year never in rationale
  (ADEA), pregnancy mention does not change score (PDA), never auto-rejects, and the
  attrition model input schema excludes all protected attributes.
- **Attrition fairness:** the model takes only six job features (no race/gender/age);
  high risk → `needs_review` for human bias review; output is advisory-only.

---

## 3. Bias & fairness (EEOC / Title VII / ADEA / PDA)

- **Demographic blinding** before resume scoring strips name, age/graduation year,
  pregnancy/maternity, gender, race, marital status (`core/guardrails.py`).
- **Name-blind disparity test** — two resumes differing only by name (e.g.
  "Lakisha" vs "Emily") score **identically**. CI gate:
  `tests/test_compliance.test_resume_name_blind_identical_scores`.
- **Never auto-rejects** — the screener returns advisory fit labels
  (`strong_fit` or `review_recommended`);
  a human decides. `test_resume_never_auto_rejects_and_no_age`.
- **Attrition takes no protected attributes** (race/gender/age not in the input
  schema) and is **advisory-only**; high risk → `needs_review` for human bias
  review. `test_attrition_no_protected_features_and_advisory`.
- **Triage escalates** harassment / discrimination / retaliation to **URGENT →
  human**, bypassing the manager. `test_triage_harassment_is_urgent_to_human`.

---

## 4. RBAC matrix

| Capability | viewer | analyst | manager | admin |
|------------|:--:|:--:|:--:|:--:|
| View dashboards / cases / audit / chat | ✅ | ✅ | ✅ | ✅ |
| Ask Policy Q&A | ✅ | ✅ | ✅ | ✅ |
| Trigger agents / screen resumes / score attrition | | ✅ | ✅ | ✅ |
| Approve / reject HITL tasks | | | ✅ | ✅ |
| Ingest / delete policies | | | ✅ | ✅ |
| Manage users & roles | | | | ✅ |

Enforced when `AUTH_ENFORCE=true` (`require_role` deps). Advisory by default for
zero-secret demos. Enforcement tested: `test_api_integration.test_rbac_enforced_blocks_then_allows`.

---

## 5. Security test matrix (application layer)

| Area | Test | Result | Where |
|------|------|--------|-------|
| Prompt injection | "ignore instructions / approve" → refused + logged | ✅ | `test_security.test_prompt_injection_blocked_and_audited` |
| Adversarial resume | hidden demographic markers stripped | ✅ | `test_security.test_adversarial_resume_hidden_text_blinded` |
| PII at rest | SSN/email not in DB file | ✅ | `test_security.test_pii_not_at_rest_in_db` |
| SQL injection | `' OR '1'='1` treated as data (parameterised) | ✅ | `test_security.test_sql_injection_is_parameterized` |
| Secret leakage | no `sk-ant-` in frontend source | ✅ | `test_security.test_no_api_key_in_frontend_source` |
| Security headers | `X-Frame-Options`/`nosniff` present | ✅ | `test_security` + live |
| RBAC escalation | no token → 401 on gated route | ✅ | `test_api_integration` |
| XSS | React escapes by default (no `dangerouslySetInnerHTML`) | ✅ | by construction |
| AuthZ horizontal isolation | per-user case ownership | ⏭ | multi-tenant roadmap (HR cases are org-scoped by role today) |
| Rate limiting / brute-force lockout | token bucket + lockout | ⏭ | gateway / SCALING.md |
| TLS in transit, container hardening | reverse proxy + prod image (non-root) | 🟡 | `Dockerfile.prod` non-root; TLS terminated upstream |

---

## 6. HR compliance checklist (status)

**GDPR / CCPA** — PII redaction ✅ · local audit + export ✅ · explicit-trigger LLM ✅ ·
data map ✅ (§2) · right-to-erasure 🟡 (manual delete; scheduled purge ⏭) ·
lawful-basis / DPIA / SCCs ⏭ (process).

**US (EEOC / FLSA / I-9)** — audit retention export ✅ · bias safeguards ✅ (§3) ·
I-9/WARN/state-law record rules ⏭ (process + connectors).

**AI-specific (EU AI Act / NYC LL144 / IL HB3579)** — human-in-the-loop on every
adverse action ✅ · model cards ✅ ([MODEL_CARDS.md](./MODEL_CARDS.md)) · bias-audit
test in CI ✅ · **no fully automated termination/rejection** ✅ · formal LL144 bias
audit by an independent auditor ⏭ (process) · EU AI Act conformity assessment ⏭ (process).

---

## 7. How to produce evidence on demand

```bash
# Audit export (CSV: timestamp, agent, action, input[redacted], output, status)
curl -s "http://localhost:8000/audit/export" -o audit_sample.csv

# Run the compliance + security gates (CI runs these on every push)
cd backend && pytest tests/test_compliance.py tests/test_security.py -v
```

Pair this file with [MODEL_CARDS.md](./MODEL_CARDS.md), [SECURITY.md](./SECURITY.md)
and [SCALING.md](./SCALING.md) for the full pack.
