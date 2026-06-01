# Open-Source Launch Guide

A checklist to publish this on GitHub and announce it on LinkedIn.

---

## 1. Pre-flight (do before pushing public)

- [ ] **Secrets**: confirm `.gitignore` excludes `.env`, `.env.local`, `*.db`,
      `backend/data/`. No real keys committed. `git log -p | grep -i key` to be sure.
- [ ] **`.env.example`** is current (it is — includes auth/Google vars).
- [ ] **LICENSE** present (MIT) and **CONTRIBUTING.md** present. ✅
- [ ] **README** top section: one-line pitch, a screenshot/GIF, quick start.
- [ ] **Backend green**: `ruff check . && black --check . && pytest -q` (33 tests).
- [ ] **Frontend green**: `npm run build && npm run lint`.
- [ ] **Seed works**: `python -m scripts.seed_data` populates a clean demo.
- [ ] Add a **SECURITY.md** with a private disclosure email.
- [ ] Add repo **topics**: `ai-agents`, `rag`, `fastapi`, `nextjs`, `hr-tech`,
      `pydantic-ai`, `langgraph`, `human-in-the-loop`, `rbac`.
- [ ] Add a short **demo GIF** (record the Chat → Cases → Approvals flow).

## 2. Push to GitHub

```bash
cd hr-command-center
git init && git add -A
git commit -m "HR AI Command Center: trustworthy, audited AI layer for HR"
git branch -M main
git remote add origin git@github.com:<you>/hr-command-center.git
git push -u origin main
```
Then in the repo settings: add the description, topics, and enable Issues +
Discussions. Pin the README sections: **Quick start**, **Architecture**,
**Walkthrough** ([WALKTHROUGH.md](./WALKTHROUGH.md)).

## 3. Repo presentation (the README hook)

Lead with the value, not the tech:

> **An AI command center for HR — safe, audited, open-source.** A team of agents
> triage tickets, answer policy questions from your docs, screen resumes,
> orchestrate onboarding, and flag attrition risk. Every action is audited, every
> sensitive step is human-approved, and it runs on your laptop with **zero secrets**.

Badges: build status, licence (MIT), Python/Node versions. Then the demo GIF,
then **Quick start**, then a link to [WALKTHROUGH.md](./WALKTHROUGH.md) and
[MISSION.md](./MISSION.md).

## 4. LinkedIn post (draft)

> 🚀 I open-sourced **HR AI Command Center** — a trustworthy AI layer for HR &
> people-ops.
>
> Most AI in HR is a black box: no audit trail, no human gate, no way to ask "why
> did this happen?" For decisions about people — pay, hiring, leave, attrition —
> that's not good enough. So I built the opposite.
>
> What it does, end to end:
> • 🧠 A chat assistant (Pydantic AI) that answers policy questions from *your*
>   documents, triages tickets, and looks up cases — with tool-call transparency
> • 🗂️ Triage that auto-resolves routine questions and **escalates urgent ones to
>   a human**
> • 📄 Resume screening, onboarding orchestration, and attrition early-warning
> • ✅ **Human-in-the-loop** approvals — and every approval *or rejection* is
>   captured with who/when/why
> • 🔒 Auth + role-based access (viewer → admin) + Google sign-in
> • 🧾 An immutable audit log you can export for compliance
>
> The part I'm proudest of: it runs **with zero secrets** in a deterministic
> fallback mode, then upgrades to LLM-grounded answers when you add an API key —
> same UI, same workflows. SQLite for dev, Postgres for prod, Docker-ready.
>
> Stack: FastAPI · Pydantic AI · LangGraph · CrewAI · Qdrant · Next.js 14 ·
> async SQLAlchemy · JWT/OAuth.
>
> It's MIT-licensed and built to be contributed to. ⭐ the repo, file an issue,
> or fork it for your own org.
>
> 👉 github.com/<you>/hr-command-center
>
> #AI #OpenSource #HRTech #LLM #RAG #Python #SoftwareEngineering #AIagents

**Tips:** attach the demo GIF (LinkedIn favours native video/images), post
Tue–Thu morning, reply to early comments fast, and cross-post in relevant
communities (r/MachineLearning "I made this", Hacker News "Show HN",
Pydantic/FastAPI Discords).

## 5. After launch

- [ ] Add a **roadmap** (link MISSION.md §Direction) and label
      `good first issue` / `help wanted` per CONTRIBUTING.md.
- [ ] Set up the GitHub Actions badge in the README (CI already exists).
- [ ] Watch the JD-alignment story in [PITCH.md](./PITCH.md) — this repo is also a
      full-stack AI-engineering portfolio piece.
- [ ] Triage incoming issues within 48h to keep momentum.
