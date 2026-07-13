# Govern.ai
## Hackathon Use Cases and Demo Walkthrough

## One-line pitch

HR teams get governed operations workflows through specialized agents that
ground work in policy, exchange certified handoffs, and keep sensitive outcomes
subject to human approval and audit.

## What is actually demoable now

Use the Fireworks online path for the live demo. The local deterministic path is
the zero-spend fallback. Do not present AMD MI300X as running in the current
environment: the repository contains an AMD/vLLM deployment contract and
preflight scripts, but no connected MI300X, ROCm runtime, or validated runtime
evidence in this preview.

Do not claim:

- Fireworks account credits from the app's local estimate
- completed Fireworks Batch work when no provider job is completed
- AMD latency, throughput, or cost wins without named hardware evidence
- autonomous hiring, firing, or employee-risk decisions

## Core use cases

### 1. Policy Q&A

```text
employee question
  -> PII/injection shield
  -> active policy retrieval
  -> Fireworks structured synthesis or deterministic fallback
  -> citation + confidence + certification
  -> answer and audit event
```

Judge moment: ask “What is the remote work policy?” and show policy sources,
confidence, the Fireworks route, and the token/cost card.

### 2. HR ticket triage

```text
incoming ticket
  -> typed category
  -> URGENT -> human queue
  -> POLICY -> grounded policy answer
  -> ONBOARDING -> onboarding workflow
  -> human override -> original label preserved + override audit event
```

Judge moment: submit an urgent payroll or safety ticket. The system escalates it
instead of pretending that automation is appropriate.

### 3. Onboarding orchestration

```text
new hire record
  -> validate
  -> create-account checklist
  -> training assignment
  -> human approval checkpoint
  -> welcome/manager notification only after approval
```

Judge moment: show the paused task in Approvals, approve it, and show the state
transition plus audit entry.

### 4. Resume screening

```text
JD + resume
  -> demographic blinding + input shield
  -> interactive online score
  -> matched/missing/unverified skills
  -> recruiter review
```

Judge moment: run the sample resume. Show that a keyword-only result is marked
`Review required: fallback mode`, while a context-validated result receives the
validated badge.

The current Resume screen is an interactive provider call. It does not create a
Batch job. The Analytics Batch panel is a real provider-job monitor only; it
shows “No provider job selected” until a real job ID is inspected. Batch calls
require `FIREWORKS_CONTROL_BASE_URL` and `FIREWORKS_ACCOUNT_ID` in addition to
the inference key.

### 5. Attrition advisory

```text
six numeric employee features
  -> RandomForest risk probability
  -> top factors + disengagement interaction
  -> manager-facing explanation
  -> threshold review
  -> human decision
```

Judge moment: adjust promotion-freeze and manager-rating inputs, show the
slow-burn disengagement factor, and emphasize that the result is advisory.

### 6. Governance and cost control

```text
every inference request
  -> token preflight
  -> allow-listed model
  -> budget/cost route
  -> provider or fallback
  -> schema/PII/grounding certifier
  -> audit and metrics
```

Judge moment: open Analytics and show provider calls, observed tokens, local
estimated spend, 8/8 cost-control evidence, injection blocks, human
escalations, and the synthetic Four-Fifths alert.

## Five-minute walkthrough

### 0:00-0:35: Problem

“HR teams are asked to use AI in sensitive workflows, but three things break:
answers lose policy grounding, cost is invisible, and high-stakes actions are
automated without a human checkpoint. This command center makes those controls
visible in the same workflow.”

### 0:35-1:25: Live policy answer

1. Open Chat.
2. Ask: `What is the remote work policy?`
3. Point to the cited documents and confidence.
4. Point to `Fireworks auth` and Analytics token telemetry.

Say: “The model generates the language, but retrieval and certification decide
whether the answer is allowed into the HR workflow.”

### 1:25-2:05: Triage and human control

1. Open Cases or Fleet.
2. Submit an urgent payroll/safety issue.
3. Show the urgent route to human review.
4. Open Approvals and approve an onboarding checkpoint.

Say: “The agent can classify and route; it cannot silently cross the human gate.”

### 2:05-2:55: Resume screening honesty

1. Open Resume Screener.
2. Load the sample.
3. Run the interactive screen.
4. Show the route label: `Interactive screening route`.
5. Show `Context-validated` or the honest fallback badge.
6. Open Analytics Batch status and show that no job is claimed until a real job
   ID exists.

Say: “A score without context validation is visibly downgraded. The product
does not turn a static batch mock into a provider success claim.”

### 2:55-3:45: Cost and safety evidence

1. Open Analytics.
2. Show provider calls, token count, local estimated spend, and cache/prefilter.
3. Show the 8/8 cost controls.
4. Show prompt-injection blocks and the bias audit ratio.

Say: “These are application-observed estimates and certification evidence, not
fabricated provider billing. Fireworks account usage is a separate provider
surface.”

### 3:45-4:30: Model and routing explanation

1. Open Settings or the capability panel.
2. Show the selected allow-listed Fireworks model.
3. Explain that `glm-5p2` is selected because it is the injected allow-listed
   runtime model, not because the UI hardcodes it as Gemma.
4. Show deterministic fallback availability.

Say: “The product can switch providers, but no route is promoted on a label
alone. It needs an allow-list, a contract, and evidence.”

### 4:30-5:00: Close

“The result is not another chatbot. It is a controlled HR operating layer:
grounded answers, typed agent handoffs, auditable human intervention, bounded
spend, and explicit degradation when a provider or deployment is unavailable.”

## Backup branches

| Live issue | Honest recovery |
|---|---|
| Fireworks unavailable | Show deterministic fallback and the provider status badge |
| Batch not configured | Show “Not configured” and explain control-plane credentials are separate from inference |
| Batch pending | Show the real pending state and explain that pending is not completion |
| AMD question | Say “The AMD/vLLM route is packaged and gated, but this demo host has no MI300X runtime evidence.” |
| Dashboard credits look empty | Explain that the app shows local budget headroom; Fireworks account credits require billing/quota integration |
| Resume context validator unavailable | Show fallback badge and discounted/unverified skills |

## Evidence checklist before recording

```text
[ ] /health says provider and config state explicitly
[ ] one live Fireworks chat response has a trace and token/cost telemetry
[ ] no secret appears in UI, logs, audit, screenshots, or evidence files
[ ] Analytics cost controls pass
[ ] bias audit is labeled synthetic evidence
[ ] Resume screen says interactive, not batch, unless a real batch job exists
[ ] Batch panel has a real provider job ID before showing a provider state
[ ] AMD is described as gated unless runtime evidence is present
[ ] final pitch uses “decision support,” never automatic employment action
```
