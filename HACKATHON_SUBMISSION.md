# Hackathon submission handoff

This is the shortest reliable path for a judge or recording operator. It runs
the complete product with synthetic data and no provider spend, then leaves the
Fireworks and AMD/Gemma claims visibly gated until their live evidence exists.

## 1. Start the reproducible container

From the repository root:

```bash
docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build
```

The overlay seeds policies, cases, chat context, and agent rows before the API
starts. It uses deterministic fallback mode (`MOCK_LLM=true`) so a missing key
cannot turn into a broken recording. In a second terminal, run:

```bash
bash scripts/hackathon_walkthrough.sh
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). The walkthrough gate must
pass before recording.

## 2. Five-minute judge walkthrough

1. **Chat / policy grounding (0:00–1:00).** Ask “What is the remote work
   policy?” Show the cited policy, confidence, and deterministic fallback badge.
2. **Cases / human control (1:00–2:00).** Open the seeded urgent payroll or
   safety case. Show that triage routes it to a human queue; approve an
   onboarding checkpoint in Approvals.
3. **Resume screening (2:00–3:00).** Upload a PDF, DOCX, HTML, JSON, or image in
   Resume Screener. Point out the parser source type, normalized skills,
   quality grade, and review warnings. Call it interactive screening; do not
   call it a completed Batch job without a provider job ID.
4. **Analytics / governance (3:00–4:00).** Show capability status, local token
   estimates, cost-control gates, audit events, and the human-review count.
   “Live-gated” is the correct status in this container.
5. **Architecture close (4:00–5:00).** Explain that the same contracts can
   route structured inference to Fireworks or a private AMD ROCm/vLLM service;
   the app keeps working when either provider is unavailable.

## Submission wording

Use this title/description hook if the form asks for the required keywords:

> **AMD powered, Gemma powered / Gamma powered, Fireworks powered — Govern.ai is a governed,
> cost-bounded HR operations layer with grounded policy answers, certified
> agent handoffs, and human approval gates.**

The accurate technical claim is **Gemma** (not “Gamma”). The AMD profile is
packaged and statically verified; use “AMD powered” as a deployment-track hook,
not as a claim that this laptop is running an AMD GPU.

## Lablab.ai form fields

Use these values for the public submission form.

**Submission title:** Govern.ai HR Command Center

**Short description:** Govern.ai coordinates HR agents for policy Q&A, ticket
triage, resume review, onboarding, and attrition signals with grounded evidence,
cost controls, and human approval gates.

**Long description:** Govern.ai is a governed HR operations layer for recruiting
and people teams. It turns separate HR automation demos into one auditable
control plane: specialized agents can answer policy questions from versioned
evidence, route urgent cases to humans, create structured resume review packets,
pause onboarding at approval checkpoints, and surface retention signals without
making autonomous employment decisions. The durable FastAPI/Postgres system
keeps working in deterministic fallback mode with no model key, while
allowlisted Fireworks or private AMD ROCm/vLLM inference can be enabled through
explicit runtime configuration. The hackathon container seeds synthetic data for
a reproducible judge walkthrough, and the AMD/Gemma deployment profile is gated
by static checks plus live runtime evidence before any hardware or performance
claim is made.

**Suggested track:** Track 3, Unicorn Track.

**Technologies:** Python, FastAPI, Next.js, TypeScript, PostgreSQL, pgvector,
Docker Compose, Fireworks AI, AMD ROCm/vLLM deployment profile, Gemma-family
model route, Pydantic AI, CrewAI, LangGraph, scikit-learn.

**GitHub repository:** https://github.com/W4sP4nx2/HR-AI-Operations

**Demo application platform:** Docker Compose / self-hosted container stack.

**Demo application URL:** No hosted demo URL is claimed in this repo state. Use
the public GitHub repository and the one-command Docker judge stack:
`docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build`.

**Cover image:** `docs/assets/govern-ai-presentation-cover.png`

**Slide deck:** `outputs/govern-ai-presentation.pptx`

## Live evidence still required for stronger claims

- Fireworks: inject the key and run `make judge-fireworks-live`.
- AMD/Gemma: run the AMD Compose profile on a named MI300X/gfx94X host, then
  run `make judge-amd-live` and retain the runtime evidence bundle.
- Performance: report hardware, ROCm/vLLM versions, model ID, prompt shape,
  dtype, p50/p95, correctness error, and memory before claiming speed or cost
  wins.

See [HACKATHON_PITCH_WALKTHROUGH.md](./HACKATHON_PITCH_WALKTHROUGH.md) for
backup branches and [HACKATHON_JUDGE_BRIEF.md](./HACKATHON_JUDGE_BRIEF.md) for
the live evidence commands.
