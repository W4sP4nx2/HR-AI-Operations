# User Manual — HR AI Command Center

For **HR and Finance teams** who use the dashboard day to day. No technical
background needed. For installation, scaling and administration, see the
[Operations Manual](./OPERATIONS_MANUAL.md).

---

## 1. What this system does

The HR AI Command Center is a single control plane where a team of AI agents help
you handle routine HR and people-operations work, while keeping a **human in the
loop** for anything sensitive and an **audit record** of everything.

The five agents:

| Agent | What it does for you |
|-------|----------------------|
| **Policy Q&A** | Answers questions from your policy documents, with citations. |
| **Triage** | Reads an incoming request and routes it: urgent → a person, policy questions → auto-answered, everything else → categorised. |
| **Resume Screener** | Scores a resume against a job description and explains the fit. *Decision-support only — it never auto-rejects.* |
| **Onboarding Orchestrator** | Runs a new-hire checklist and **pauses for your approval** before sending anything. |
| **Attrition Predictor** | Flags retention risk and suggests a conversation. *Advisory only.* |

---

## 2. The dashboard at a glance

A sidebar on the left switches between five panels. The top bar always shows
**System Healthy / Offline** and how many agents are currently active.

| Panel | Use it to… |
|-------|-----------|
| **Fleet** | See every agent's status and **trigger** one with text, a PDF, or a link. |
| **Cases** | Watch incoming cases update **live**, filter by category/status. |
| **Analytics** | See KPIs (cases resolved, time saved) and risk charts. |
| **Audit** | Review every action taken and **export it as CSV**. |
| **Approvals** | Approve or reject anything an agent paused for your sign-off. |

---

## 3. Triggering an agent (text, PDF, or link)

On the **Fleet** panel, each agent card has an input row. You can give it work in
three ways:

1. **Type or paste text** — e.g. a question, a ticket, or a paragraph of a resume.
2. **Attach a PDF** — click the 📎 paperclip and choose a file (resume, policy,
   exported ticket). The filename appears below the row.
3. **Paste a link** — paste a URL (starting `http://` or `https://`) and the
   system will read the page's text for you.

Then click **Trigger**. A coloured result chip appears underneath:

| Chip | Meaning | What to do |
|------|---------|-----------|
| 🟢 **Success** | The agent ran and produced a result (shown in the chip). | Nothing — check Cases/Audit for detail. |
| 🔴 **Failed** | The request couldn't be processed (e.g. empty input, unreadable PDF, wrong link). | Read the message and try again with valid input. |
| 🟡 **Unavailable** | A capability isn't switched on right now (e.g. link-reading not configured, or no AI key for deep answers). | Try a different input, or ask your administrator (see Ops Manual). |

The chip also shows what the system received — for example **"text · 53 chars"**
or **"pdf · 1,240 chars"** — so you always know *what was passed in*.

> **Tip — Resume Screener:** attach the candidate's resume as a PDF and type the
> **job description** in the text box. The system screens the resume against it.

---

## 4. Worked examples

### Answer a policy question
Fleet → **Policy Q&A** → type *"How many vacation days do I get?"* → **Trigger**.
The Success chip shows the answer; full text and sources are in **Audit**.

### Handle an urgent ticket
Fleet → **Triage** → paste the ticket text → **Trigger**.
If it's urgent (e.g. "payroll fails today"), the chip reads
**"Triaged as URGENT → escalated"** and a red **URGENT** case appears in **Cases**,
assigned to a human.

### Screen a candidate
Fleet → **Resume Screener** → 📎 attach the resume PDF → type the job description →
**Trigger**. The chip shows e.g. **"Score 95 · hire"** with matched/missing skills.

### Onboard a new hire
Fleet → **Onboarding Orchestrator** → type the new hire's name → **Trigger**.
The chip reads **"Paused for human approval"**. Go to **Approvals**, review the
prepared accounts/training, and **Approve** (or **Reject** with a reason). Only
after you approve does the welcome email send and the manager get notified.

---

## 5. Approvals (human-in-the-loop)

Anything that *writes* or is *sensitive* stops at the **Approvals** panel before it
happens. Each pending card shows exactly what's about to occur (e.g. which
accounts will be created, which email will be sent).

- **Approve** — the workflow resumes and completes. Add a short reason; it's saved
  to the audit trail.
- **Reject** — the workflow stops and goes back with your reason. Nothing
  sensitive runs.

---

## 6. Cases and their stages

Every request becomes a **case** that moves through clear stages:

```
Received → Triaged → (Auto-resolved)            ← policy questions answered by AI
                   → (Open / In progress)        ← categorised, queued for a person
                   → (Awaiting approval)         ← paused for your sign-off
                   → Resolved  /  Escalated      ← closed, or handed to a human
```

In the **Cases** panel, the coloured chips tell you the category (e.g. URGENT,
BENEFITS, POLICY) and the status. The **LIVE** badge means new cases appear
instantly, no refresh needed.

---

## 7. Audit & compliance (for HR and Finance)

The **Audit** panel is your system of record. Every agent action — what came in,
what the agent did, the outcome, and when — is logged automatically and cannot be
skipped. Use **Export CSV** for monthly reporting, audits, or to hand to
compliance/finance. Filter by agent to narrow it down.

This is what makes the automation **defensible**: for any decision, you can show
who/what did it, on what input, and who approved it.

---

## 8. Good practice

- **Trust but verify** — agents are assistants. Resume scores and attrition flags
  are decision-support; a person always makes the final call.
- **Use approvals** — never bypass the Approvals step for onboarding/offboarding.
- **Keep policies current** — Policy Q&A is only as good as the documents loaded
  (your administrator manages these; see Ops Manual §"Loading policies").
- **Mind sensitive data** — attrition and personal data are access-controlled;
  follow your organisation's data-handling rules.

---

## 9. Quick troubleshooting

| You see… | Likely cause | Fix |
|----------|--------------|-----|
| **System Offline** (top bar) | The backend isn't reachable. | Wait a moment; if it persists, tell your administrator. |
| 🟡 **Unavailable** after a link | Page-reading not configured/reachable. | Copy the text in directly, or ask your admin to enable scraping. |
| 🟡 **Unavailable** on an answer | No AI key configured; running in basic mode. | Still works in a simpler way; admin can enable full AI answers. |
| 🔴 **Failed: no extractable text** | The PDF is scanned/image-only. | Use a text-based PDF, or paste the text. |
| Empty answer / "No relevant policy found" | No policy documents loaded yet. | Ask your admin to load policy PDFs. |
