# Workflows, Agent Data Flows & Current Gaps

Grounded in the actual code (not aspirational). Answers the open questions: when
cases are auto-assigned, how you know a case is solved, what each agent does and
how its success is measured, the resume-score "30" question, and the missing
undo-on-delete — then states the clear, structured target workflow.

---

## 1. The spine — end-to-end workflow today

```
 Upload policy PDF ─▶ extract (pypdf) ─▶ chunk (512/50) ─▶ embed (MiniLM/hashing)
                                                              │
                                                              ▼
                                              pgvector  policy_chunks  (HNSW cosine)
                                                              ▲
 Inbound (UI / chat / webhook) ─▶ TRIAGE classifies ─┐        │ top-k retrieval
                                                      ▼        │
                                  creates CASE (auto-assigned + auto-status)
                                                      │
                    ┌─────────────────────────────────┼───────────────────────────┐
                    ▼                                  ▼                            ▼
            Cases feed (live)                   Analytics (aggregates)         Audit (immutable)
            click → detail drawer               KPIs + charts from /cases      every action + decision
```

Everything an agent does is **audited**; cases drive **Analytics**; the **Audit**
trail is the system of record. That loop is the product.

---

## 2. When are cases auto-assigned? (and the status rules)

**Triage assigns every case at creation** (`agents/triage_agent.py`). The rule:

| Category | Status set | Assigned to | Auto-resolved? |
|----------|-----------|-------------|----------------|
| **URGENT** (harassment / discrimination / payroll-down / safety) | `escalated` | `human` | No — waits for a person |
| **POLICY** (answerable from docs) | `resolved` | `policy_qa_agent` | **Yes** — answered via RAG |
| BENEFITS / ONBOARDING / PERFORMANCE / COMPLIANCE | `open` | `triage_agent` | No — queued |

So assignment is **automatic and rule-based** at intake. The gap: that rule is
invisible in the UI (you can't see *why* a case went where it did) — see G2.

---

## 3. How do I know a case is solved? (the honest gap)

**Today: you mostly can't, manually.** A case becomes `resolved` only when Triage
**auto-resolves a POLICY case**, or an onboarding task is **approved**. There is
**no "Mark solved / Resolve" button** and **no `PATCH /cases/{id}/status`
endpoint** — an `open` or `escalated` case can't be closed from the dashboard.
That's the #1 workflow gap (**G1**).

---

## 4. Each agent: trigger → data flow → case link → demo success signal

| Agent | Trigger | Data flow | Touches a case? | **Demo success = ** |
|-------|---------|-----------|-----------------|---------------------|
| **Triage** | ticket text (UI/chat/webhook) | classify (keyword/LLM) → route | **creates** the case | "I'm being harassed" → **URGENT · escalated · human** (and a row appears live in Cases) |
| **Policy Q&A** | question | embed → pgvector top-k → synth (Claude/excerpt) → `confidence`, `needs_review` | resolves POLICY cases | "vacation days?" → **cited answer** with `confidence`; low conf → `needs_review` |
| **Resume Screener** | JD + resume (text/PDF) | **demographic-blind** → embed similarity + skill match → score 0–100 | no (decision-support) | strong resume → **score ≥ 65 · hire**; Lakisha == Emily (blind) |
| **Onboarding Orchestrator** | new-hire record | validate → create-accounts → assign-training → **PAUSE** | creates a paused approval task | reaches **"paused"**, then Approve → `welcome_sent`, audited |
| **Attrition Predictor** | 6 features | RandomForest → risk + top drivers + explanation | no (advisory) | at-risk profile **scores higher** than healthy; `advisory_only`, high → `needs_review` |

**Each is independently demonstrable** — the success signal column is exactly what
to show in a 6-beat walkthrough.

---

## 5. The resume-score "30" question (clarified)

> *"Is score 30 the default before policies are uploaded and Anthropic connected?
> Someone can type 'john' and get a score."*

Three clarifications:

1. **The Resume Screener does not use policies at all.** It scores **resume vs. job
   description** only. The policy vector DB is irrelevant to it — uploading policies
   changes nothing here.
2. **The number doesn't need Anthropic.** `score = round(100 × (0.6·semantic +
   0.4·keyword_match))` is computed deterministically (embedding similarity + skill
   keywords). Anthropic/CrewAI only adds a *narrative*; the number is the same.
   So **~30 is the floor for thin/unrelated input** (e.g. "john" → low semantic fit,
   0 skill match), **not** a "no data" default.
3. **Real gap (G3):** the screener accepts a one-word input like "john" and returns
   a confident-looking number with no guardrail. It should require a minimum input
   and flag low-confidence ("insufficient input — not a valid assessment").

---

## 6. Current gaps (honest, with the *minimal* fix — not overengineered)

| # | Gap | Status | Fix shipped |
|---|-----|--------|-------------|
| **G1** | No manual Resolve / Reopen | ✅ **Fixed** | `PATCH /cases/{id}/status` (analyst+, audited, broadcast) + **Mark resolved / Reopen** button in the case drawer |
| **G2** | Auto-assignment is invisible | ⏭ open | Surface the routing reason on the case (already in the data) — pure UI |
| **G3** | Resume accepts trivial input ("john") | ✅ **Fixed** | Input guard (<8 resume / <3 JD words) → `score 0`, `needs_review`, "insufficient input" reasoning; Fleet chip shows "⚠ Needs review" |
| **G4** | Policy delete is permanent — no undo | ✅ **Fixed** | **Soft-delete** (`status='deleted'`, vectors purged, `source_text` retained) + `POST /policies/{id}/restore` re-embeds; **Undo** action on the delete toast |
| **G5** | Analytics starved of resolutions | 🟡 unblocked by G1 | Now that humans can resolve cases, KPIs populate; hours-saved/avg-time still estimates (label them) |
| **G6** | Case lifecycle/stages not shown | ⏭ open | Render stage chips (Received → Triaged → Open/Awaiting-approval → Resolved/Escalated) — pure UI |

Everything else (intake, triage, RAG, approvals, audit, RBAC) already works — these
six are the responsiveness/closure gaps, and all six fixes are small.

---

## 7. The clear, structured target workflow (responsive, not overengineered)

```
1. Admin/manager uploads policy PDFs ──▶ chunked + embedded into pgvector
                                          (delete = soft-delete; Restore re-embeds)   ← G4
2. Inbound request (UI / chat / webhook) ──▶ Triage classifies
        URGENT  ──▶ case: escalated → human            (reason shown)                  ← G2
        POLICY  ──▶ RAG answer ──▶ case: resolved (cited, confidence)
        other   ──▶ case: open → queued
3. Human works an open case in the drawer ──▶ **Resolve / Reopen** button             ← G1
4. Resume screen / attrition run ──▶ advisory output (never auto-acts; input-guarded) ← G3
5. Every step ──▶ Audit (immutable, PII-redacted)
6. Cases (with real resolution events) ──▶ Analytics KPIs + charts                     ← G5
```

**Fleet view stays the cockpit** (status, last action, runs, manual trigger);
**Cases** is the live work queue with a closure action; **Analytics** is the
outcome layer fed by real resolutions; **Audit** is the ledger. Clear, linear,
responsive — no extra orchestration layers.

---

## 8. Recommended order to close the gaps (½–1 day)
1. **G1** Resolve/Reopen endpoint + button (unblocks G5 too).
2. **G4** Policy soft-delete + Restore (the "undo" you asked for).
3. **G3** Resume input guard + low-confidence flag.
4. **G2 / G6** Surface routing reason + stage chips (pure UI, already in the data).

> Want me to implement G1 + G4 + G3 now? They're contained: one new endpoint + a
> button each, plus a soft-delete column on `policies`. No new infrastructure.
