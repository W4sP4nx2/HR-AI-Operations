"""Seed Govern.ai with sample policies, cases and a chat demo.

Run from the backend directory (with the venv active)::

    python -m scripts.seed_data

What it does
------------
1. Generates twelve deterministic policy PDFs in ``sample_data/policies/``.
2. Ingests them via the policy pipeline (registry + vector store if available).
3. Files a set of sample HR tickets through the Triage agent (creates cases).
4. Runs a few chat turns through the assistant and prints the transcript.

Everything works with no API key (deterministic fallbacks). With
``ANTHROPIC_API_KEY`` + Qdrant the same script produces LLM-grounded results.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# --------------------------------------------------------------------------- #
# Sample content
# --------------------------------------------------------------------------- #

SAMPLE_POLICIES: dict[str, str] = {
    "annual_leave_policy.pdf": (
        "Annual Leave Policy. Full-time employees accrue 20 days of paid annual "
        "leave per calendar year, accruing monthly. Up to 5 unused days may be "
        "carried over into the next year. Leave requests must be submitted at "
        "least 2 weeks in advance and approved by the line manager. Unused leave "
        "beyond the carry-over limit is forfeited at year end."
    ),
    "policy_pto_2023.pdf": (
        "Paid Time Off Policy. Effective 2023-01-01 and expired 2023-12-31. "
        "Employees get 15 days PTO per calendar year."
    ),
    "policy_pto_2024.pdf": (
        "Paid Time Off Policy. Effective 2024-01-01 and active. Employees get "
        "25 days PTO per calendar year."
    ),
    "parental_leave_policy.pdf": (
        "Parental Leave Policy. Primary caregivers are entitled to 12 weeks of "
        "fully paid parental leave following the birth or adoption of a child. "
        "Secondary caregivers receive 4 weeks of fully paid leave. Leave must be "
        "taken within 12 months of the birth or adoption. Employees should notify "
        "HR at least 30 days before the intended start date."
    ),
    "remote_work_policy.pdf": (
        "Remote Work Policy. Employees may work remotely up to 3 days per week "
        "with manager approval. A stable internet connection and a secure work "
        "environment are required. Core collaboration hours are 10am to 3pm local "
        "time. Company equipment must be used for all work involving confidential "
        "data. Fully remote arrangements require department head approval."
    ),
    "benefits_enrollment.pdf": (
        "Benefits Enrollment. New employees must enroll in health, dental and "
        "vision plans within 30 days of their start date. Open enrollment occurs "
        "each November for the following year. The company contributes 80 percent "
        "of the health premium for employees and 50 percent for dependents. A 401k "
        "match of up to 4 percent of salary is available after 90 days of service."
    ),
    "code_of_conduct.pdf": (
        "Code of Conduct. All employees must treat colleagues with respect and "
        "maintain a harassment-free workplace. Conflicts of interest must be "
        "disclosed to HR. Confidential company and customer information must be "
        "protected at all times. Violations may result in disciplinary action up "
        "to and including termination. Concerns can be reported confidentially to "
        "the HR compliance team."
    ),
    "expense_reimbursement.pdf": (
        "Expense Reimbursement Policy. Business expenses must be submitted within "
        "30 days with itemised receipts. Meals are reimbursed up to 50 dollars per "
        "day during travel. Economy airfare and standard hotel rooms are covered. "
        "Personal expenses, alcohol and fines are not reimbursable. Manager "
        "approval is required for any single expense over 500 dollars."
    ),
    "performance_review.pdf": (
        "Performance Review Policy. Formal reviews occur twice a year, in June and "
        "December. Ratings range from 1 (needs improvement) to 5 (outstanding). "
        "Promotions and merit increases are tied to documented performance and "
        "manager recommendation. Employees rated 2 or below are placed on a "
        "performance improvement plan with clear goals and a 90-day review."
    ),
    "health_and_safety.pdf": (
        "Health and Safety Policy. Employees must report workplace injuries to HR "
        "within 24 hours. Ergonomic assessments are available on request. Fire "
        "drills are conducted quarterly. Remote workers are responsible for a safe "
        "home workspace. Serious hazards must be reported immediately and work in "
        "the affected area paused until cleared."
    ),
    "equal_opportunity.pdf": (
        "Equal Opportunity Policy. The company hires and promotes without regard to "
        "race, colour, religion, sex, national origin, age, disability, pregnancy "
        "or marital status. Hiring decisions are based on qualifications and fit "
        "for the role. Complaints of discrimination are investigated promptly and "
        "confidentially, and retaliation is strictly prohibited."
    ),
    "data_protection.pdf": (
        "Data Protection Policy. Employee personal data is processed only for "
        "legitimate HR purposes and retained no longer than necessary. Access is "
        "restricted by role. Employees may request a copy of, or deletion of, "
        "their personal data. Suspected data breaches must be reported to the data "
        "protection officer without undue delay."
    ),
}

SAMPLE_TICKETS: list[str] = [
    "I cannot access the payroll portal and salaries run today, this is urgent!",
    "How do I enroll in the dental plan as a new joiner?",
    "What is the company policy on carrying over unused vacation days?",
    "I'd like to report a harassment concern about a team member, confidential please.",
    "My onboarding training modules are not showing up in the system.",
    "Can I work remotely 4 days a week from next month?",
    "My manager has not completed my mid-year review and the promotion cycle closes Friday.",
    "I need to update my dependent after a qualifying life event; which benefits documents are required?",
    "A former contractor still appears to have access to an employee folder. Please route this as a compliance concern.",
    "The expense portal rejected a business meal with an itemised receipt. What is the appeal process?",
    "I am returning from parental leave and need the policy for phased hours and manager approval.",
    "A new hire cannot access the security training assignment after their account was created.",
    "Can I request an ergonomic assessment for my home workspace and is equipment covered?",
    "My team is being asked to work through a scheduled rest day without written approval.",
    "Where can I report a suspected breach involving employee personal data?",
    "I have been placed on a performance plan and need to understand the review timeline.",
    "My health plan enrollment window closes tomorrow and the benefits portal is unavailable.",
    "Please explain the conflict-of-interest disclosure process for a supplier relationship.",
    "I need to take bereavement leave next week and want to confirm the notice requirements.",
    "The remote-work request form is missing the department-head approval option.",
]

SAMPLE_CHAT_PROMPTS: list[str] = [
    "How many PTO days do I have?",
    "How many vacation days do I get each year?",
    "Our HRIS is down and payroll fails in an hour, urgent!",
    "What is the parental leave entitlement for a primary caregiver?",
    "List all open urgent cases",
    "What documentation is needed to add a dependent outside open enrollment?",
    "How many days do I have to submit a reimbursable travel expense?",
    "Who can approve a fully remote arrangement?",
    "What happens after a performance rating of two?",
    "How do I report a suspected employee data breach?",
    "Can a secondary caregiver take parental leave in separate blocks?",
    "What are the core collaboration hours for remote employees?",
    "Where should I report a harassment concern if my manager is involved?",
    "Can I request a home-office ergonomic assessment?",
    "What is the process for a promotion review that was missed?",
    "How quickly must a workplace injury be reported?",
    "Are personal expenses or fines reimbursable during business travel?",
    "How do I request a copy of my employee data?",
    "What does a performance improvement plan include?",
]


def expand_demo_policy(filename: str, summary: str) -> str:
    """Build a substantial, sectioned synthetic policy fixture for local demos.

    The original seed copy was tiny and made every PDF appear as one retrieval
    chunk. These sections keep the fixture synthetic while exercising 500-token
    windows with 50-token overlap in the actual product preview.
    """
    title = filename.removesuffix(".pdf").replace("_", " ").title()
    return f"""{title}

{summary}

Scope and eligibility. This synthetic HR policy applies to employees covered by
the relevant programme and should be read with the employee handbook, local
law, and any written employment agreement. Contractors and contingent workers
follow the terms in their engagement letter unless HR records an exception.
Employees should ask People Operations when a role, location, employment type,
or transfer creates uncertainty about eligibility. The policy owner publishes
the current version and retires older copies.

Request workflow. Employees start a request in the HR portal or through their
People Partner and provide dates, business reason, supporting documents, and the
manager needed for review. A manager checks team coverage and confirms the
request in the system. HR validates eligibility when the request affects pay,
benefits, leave balances, access rights, or a regulated record. A portal
confirmation is the source of truth; a chat message alone is not an approval.

Manager responsibilities. Managers apply the same documented criteria to
comparable requests, respond within the service window, and avoid asking for
information that is not necessary for the decision. When a request cannot be
approved, the manager records a concise reason and points the employee to the
appeal or escalation route. Managers must not retaliate against an employee for
raising a concern or asking HR to review a case.

Exceptions and escalation. Urgent safety, payroll, access, privacy, or legal
issues bypass the normal queue and go to the appropriate human team. A policy
exception requires a written business reason, an accountable approver, and an
expiry or review date. People Operations may request additional evidence, but
the employee should receive a clear explanation of what is needed and why.
Conflicting versions are escalated to the policy owner rather than resolved by
guesswork or an outdated document.

Records and privacy. HR stores only the minimum information needed to process
the request, restricts access by role, and retains the record according to the
data protection schedule. Sensitive identifiers should not be copied into open
chat channels. Employees may ask how a record is used, request correction of
an inaccurate record, or report suspected unauthorised access to the data
protection officer. Audit events record the action and outcome, not unnecessary
personal details.

Review and appeals. If an employee believes the policy was applied incorrectly,
they may ask their People Partner for a review and include the confirmation,
relevant dates, and a short explanation. The reviewer checks the effective
version, eligibility, approvals, and any local requirements. A review does not
guarantee a different outcome, but it must produce a documented decision and a
next step. Policy owners review this fixture at least annually and whenever a
law, benefit plan, system, or operating process changes.

Operational checklist. Before closing a request, confirm that the employee's
question was understood, the active policy version was used, required approval
was recorded, the employee received a concise answer, and any follow-up owner
has been named. Cases involving potential harm, discrimination, privacy loss,
or payroll impact remain visible to a human reviewer even when an AI agent
provides a grounded draft response. This synthetic text is for local product
evaluation and is not a substitute for company policy or legal advice."""


# --------------------------------------------------------------------------- #
# Minimal valid PDF generator (no external deps)
# --------------------------------------------------------------------------- #


def make_pdf(text: str) -> bytes:
    """Build a minimal, valid single-page PDF containing ``text``."""
    # Wrap text across multiple lines so longer policies render on the page.
    words = text.split()
    lines: list[str] = []
    cur = ""
    for w in words:
        if len(cur) + len(w) + 1 > 90:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)

    content = "BT /F1 11 Tf 50 740 Td 14 TL\n"
    for ln in lines:
        safe = ln.replace("(", "\\(").replace(")", "\\)")
        content += f"({safe}) Tj T*\n"
    content += "ET"
    stream = content.encode("latin-1", "replace")

    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(pdf))
        pdf += str(i).encode() + b" 0 obj" + obj + b"endobj\n"
    xref_pos = len(pdf)
    pdf += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        pdf += ("%010d 00000 n \n" % off).encode()
    pdf += (
        b"trailer<</Size "
        + str(len(objs) + 1).encode()
        + b"/Root 1 0 R>>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF"
    )
    return pdf


# --------------------------------------------------------------------------- #
# Seeding steps
# --------------------------------------------------------------------------- #


def write_policy_pdfs(directory: str) -> list[str]:
    """Write the sample policy PDFs to ``directory``; return their paths."""
    os.makedirs(directory, exist_ok=True)
    paths = []
    for name, text in SAMPLE_POLICIES.items():
        path = os.path.join(directory, name)
        with open(path, "wb") as f:
            f.write(make_pdf(expand_demo_policy(name, text)))
        paths.append(path)
    return paths


async def ingest_policies(paths: list[str]) -> None:
    """Ingest each policy PDF (registry + vector store if available)."""
    from core.memory import memory
    from pipelines.ingestion import chunk_document
    from pipelines.intake import extract_text_from_pdf_bytes
    from services import rag

    print("\n=== Policies ===")
    for path in paths:
        with open(path, "rb") as f:
            data = f.read()
        text = extract_text_from_pdf_bytes(data)
        doc_id = os.path.basename(path).replace(".pdf", "")
        plan, chunks = chunk_document(text, doc_id=doc_id, source=path)
        written = await rag.ingest_chunks(chunks)
        await memory.upsert_policy(
            doc_id=doc_id,
            filename=os.path.basename(path),
            chunks=len(chunks),
            char_count=len(text),
            status="ingested" if written else "vector_store_unavailable",
            source_text=text,
        )
        flag = f"→ {written} vectors" if written else "→ registry only (no vector backend)"
        print(f"  ✓ {os.path.basename(path):28} {len(chunks)} chunks " f"[{plan.strategy}]  {flag}")


async def file_tickets() -> None:
    """Run sample tickets through Triage to create cases (idempotent).

    Re-running the seed must not pile up duplicate cases, so we skip any ticket
    whose exact text already has a case on file. The audit log is append-only by
    design, so we de-duplicate the *cases*, not the audit trail.
    """
    from agents.triage_agent import triage_agent
    from core.memory import memory

    print("\n=== Cases (via Triage) ===")
    for ticket in SAMPLE_TICKETS:
        existing = await memory.find_case_by_detail(ticket)
        if existing:
            print(f"  • {existing['id']:16} {existing.get('category', '?'):11} (exists, skipped)")
            continue
        result = await triage_agent.run(ticket)
        case = result.get("case", {})
        print(
            f"  ✓ {case.get('id', '?'):16} {result.get('category', '?'):11} "
            f"{case.get('status', '?'):10} {ticket[:50]}"
        )


async def run_chat_demo() -> None:
    """Run a few chat turns and print the transcript.

    Idempotent: one of the prompts is an urgent ticket that triage turns into a
    case, so on a re-seed we skip the whole transcript if that case already
    exists — otherwise every re-run would leak another case.
    """
    from agents.chat_agent import chat
    from core.memory import memory

    urgent_prompt = "Our HRIS is down and payroll fails in an hour, urgent!"
    if await memory.find_case_by_detail(urgent_prompt):
        print("\n=== Chat transcript === (already seeded, skipped)")
        return

    print("\n=== Chat transcript ===")
    history: list[dict[str, str]] = []
    for prompt in SAMPLE_CHAT_PROMPTS:
        result = await chat(prompt, history)
        tools = ", ".join(
            tc.get("tool") or tc.get("name", "") for tc in result.get("tool_calls", [])
        )
        reply = result["reply"].replace("\n", " ")
        print(f"\n  👤 {prompt}")
        print(f"  🔧 tools: {tools or '—'}  ({result['mode']})")
        print(f"  🤖 {reply[:160]}")
        history.append({"role": "user", "content": prompt})
        history.append({"role": "assistant", "content": result["reply"]})


async def main() -> None:
    """Run the full seed."""
    here = os.path.dirname(__file__)
    policies_dir = os.path.join(here, "..", "sample_data", "policies")

    print("Seeding Govern.ai with sample data…")
    paths = write_policy_pdfs(policies_dir)
    print(f"  Wrote {len(paths)} policy PDFs to sample_data/policies/")

    await ingest_policies(paths)
    await file_tickets()
    await run_chat_demo()

    print("\n✅ Seed complete. Open the dashboard and explore Policies, Cases and Chat.")


if __name__ == "__main__":
    asyncio.run(main())
