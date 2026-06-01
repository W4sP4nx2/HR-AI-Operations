"""Resume Screener agent built with CrewAI.

A crew of three role-specialised agents:
    * JD Parser Agent       — extracts required skills from the job description.
    * Resume Scorer Agent   — scores the resume 0-100 against JD requirements.
    * Recommendation Agent  — writes a hire / no-hire recommendation.

Semantic similarity scoring uses HuggingFace sentence-transformers. CrewAI is
used to orchestrate the agents when available; when CrewAI (or an LLM key) is
not present, the agent falls back to a deterministic embedding-based scorer so
the endpoint always returns the structured JSON contract.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from agents.resume_resolver import resume_resolver
from core.config import settings
from core.embeddings import embedder
from core.memory import memory

AGENT_NAME = "resume_screener_agent"

# Candidate skill tokens: a letter-led term that may contain inner +/#/.-/digits
# (c++, c#, node.js, ci-cd). Trailing punctuation is stripped separately so
# "testing." and "databases." don't leak in as bogus skills.
_SKILL_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]*")

# Filler that is *not* a skill. Beyond generic English stopwords this drops the
# boilerplate that pollutes job descriptions ("senior", "required", "nice to
# have", …) so the matched/missing skill lists stay meaningful rather than
# treating every word in the JD as a requirement.
_STOPWORDS = {
    # generic
    "and",
    "the",
    "for",
    "with",
    "you",
    "our",
    "are",
    "this",
    "that",
    "will",
    "have",
    "your",
    "from",
    "must",
    "should",
    "experience",
    "years",
    "work",
    "who",
    "can",
    "all",
    "any",
    "into",
    "etc",
    "via",
    "per",
    # JD boilerplate / seniority / framing
    "senior",
    "junior",
    "lead",
    "principal",
    "staff",
    "mid",
    "entry",
    "level",
    "required",
    "require",
    "requires",
    "preferred",
    "prefer",
    "nice",
    "plus",
    "bonus",
    "want",
    "wanted",
    "looking",
    "seeking",
    "ideal",
    "candidate",
    "role",
    "team",
    "teams",
    "ability",
    "able",
    "strong",
    "solid",
    "proven",
    "good",
    "great",
    "excellent",
    "deep",
    "hands",
    "knowledge",
    "skills",
    "skill",
    "proficiency",
    "proficient",
    "familiar",
    "familiarity",
    "using",
    "use",
    "build",
    "building",
    "built",
    "design",
    "designing",
    "develop",
    "developing",
    "working",
    "responsible",
    "responsibilities",
    "including",
    "such",
    "well",
    "across",
    "within",
    "around",
    "recent",
    "recently",
}

# Skill-ish tokens shorter than 3 chars we still want to keep (real tech names).
_SHORT_SKILLS = {"go", "ml", "ai", "qa", "ci", "ci/cd", "r", "c", "c#", "c++"}


def _extract_skill_terms(text: str) -> list[str]:
    """Extract a deduplicated list of candidate skill terms from text.

    Args:
        text: Source text (job description or resume).

    Returns:
        Lower-cased, de-duplicated candidate terms with punctuation and
        boilerplate stopwords removed.
    """
    seen: list[str] = []
    for raw in _SKILL_PATTERN.findall(text):
        t = raw.lower().strip(".-")  # drop trailing sentence punctuation / dashes
        if not t or t in _STOPWORDS or t in seen:
            continue
        if len(t) >= 3 or t in _SHORT_SKILLS:
            seen.append(t)
    return seen


class ResumeScreenerAgent:
    """Screens resumes against a job description and recommends a decision."""

    def __init__(self) -> None:
        """Initialise the screener."""

    # -- crew construction ------------------------------------------------
    def _build_crew(self, jd: str, resume: str):
        """Construct a CrewAI crew, or return None to use the fallback.

        Args:
            jd: Job description text.
            resume: Candidate resume text.

        Returns:
            A configured ``Crew`` instance or ``None``.
        """
        if not settings.anthropic_api_key:
            return None
        try:
            from crewai import Agent, Crew, Process, Task

            llm = f"anthropic/{settings.claude_model}"
            jd_parser = Agent(
                role="JD Parser",
                goal="Extract the required skills from the job description.",
                backstory="An expert technical recruiter who distils JDs into skills.",
                llm=llm,
                verbose=False,
            )
            scorer = Agent(
                role="Resume Scorer",
                goal="Score the resume 0-100 against the required skills.",
                backstory="A meticulous evaluator of candidate-role fit.",
                llm=llm,
                verbose=False,
            )
            recommender = Agent(
                role="Recommendation Writer",
                goal="Write a hire/no-hire recommendation with clear reasoning.",
                backstory="A hiring manager who writes concise, fair decisions.",
                llm=llm,
                verbose=False,
            )
            t1 = Task(
                description=f"Extract required skills from this JD:\n{jd}",
                expected_output="A comma-separated list of required skills.",
                agent=jd_parser,
            )
            t2 = Task(
                description=f"Score this resume 0-100 against the JD:\n{resume}",
                expected_output="A single integer score 0-100 with brief notes.",
                agent=scorer,
            )
            t3 = Task(
                description="Write a hire or no-hire recommendation with reasoning.",
                expected_output="A short recommendation paragraph.",
                agent=recommender,
            )
            return Crew(
                agents=[jd_parser, scorer, recommender],
                tasks=[t1, t2, t3],
                process=Process.sequential,
                verbose=False,
            )
        except Exception:  # noqa: BLE001
            return None

    # -- deterministic fallback ------------------------------------------
    def _embedding_score(self, jd: str, resume: str) -> dict[str, Any]:
        """Score a resume against a JD using sentence-transformer similarity.

        Args:
            jd: Job description text.
            resume: Resume text.

        Returns:
            The structured screening result dict.
        """
        jd_skills = _extract_skill_terms(jd)
        resume_terms = set(_extract_skill_terms(resume))

        def _present(skill: str) -> bool:
            """Match a JD skill against the resume, tolerating plurals/stems.

            Exact match, or a prefix match for terms long enough that a shared
            4+ char stem is meaningful (api↔apis, test↔testing) — without
            collapsing short distinct tokens (go, ml).
            """
            if skill in resume_terms:
                return True
            if len(skill) < 4:
                return False
            return any(
                rt.startswith(skill) or skill.startswith(rt) for rt in resume_terms if len(rt) >= 4
            )

        matched = [s for s in jd_skills if _present(s)]
        missing = [s for s in jd_skills if not _present(s)]

        # Input guard: a one-word "resume" (e.g. "john") or an empty JD is not a
        # valid assessment — flag for review instead of returning a confident score.
        resume_tokens = len(resume.split())
        jd_tokens = len(jd.split())
        insufficient = resume_tokens < 8 or jd_tokens < 3
        if insufficient:
            return {
                "score": 0,
                "recommendation": "no-hire",
                "reasoning": (
                    "Insufficient input to assess — provide a full resume and job "
                    f"description (got {resume_tokens} resume / {jd_tokens} JD words). "
                    "This is not a valid screening."
                ),
                "matched_skills": matched,
                "missing_skills": missing,
                "needs_review": True,
            }

        semantic = embedder.similarity(jd, resume)  # 0..1
        total = len(jd_skills)
        keyword_ratio = len(matched) / total if total else 0.0
        # Round half-up everywhere (matches JS Math.round) so the gauge, the
        # coverage % and the matched/total counts are all mutually consistent —
        # no banker's-rounding drift (e.g. 10/16 = 62.5% shows as 63%, not 62%).
        score = int(100 * (0.6 * semantic + 0.4 * keyword_ratio) + 0.5)
        coverage = int(keyword_ratio * 100 + 0.5)

        recommendation = "hire" if score >= 65 else "no-hire"
        # State the blend explicitly so the 0.66 semantic and the 65 gauge aren't
        # mistaken for the same number — the gauge is a weighted blend of both.
        reasoning = (
            f"Overall fit {score}/100 — a blend of semantic similarity {semantic:.2f} "
            f"and keyword coverage {coverage}% ({len(matched)}/{total} required skills "
            f"matched). {'Strong' if score >= 65 else 'Limited'} alignment."
        )
        return {
            "score": score,
            "recommendation": recommendation,
            "reasoning": reasoning,
            "matched_skills": matched,
            "missing_skills": missing,
            "needs_review": False,
        }

    # -- public API -------------------------------------------------------
    async def run(self, job_description: str, resume: str) -> dict[str, Any]:
        """Screen a resume against a job description.

        Args:
            job_description: The job description text.
            resume: The candidate's resume text.

        Returns:
            Structured JSON: ``score``, ``recommendation``, ``reasoning``,
            ``matched_skills``, ``missing_skills``.
        """
        await memory.upsert_agent(AGENT_NAME, status="running", last_action="screening resume")
        # Demographic blinding: strip name/age/pregnancy/protected attributes so the
        # score is name- and demographic-invariant (Title VII / ADEA / PDA / EEOC).
        from core.guardrails import blind_demographics

        raw_resume = resume  # retained only for the timeline pass (not scored, not stored)
        resume = blind_demographics(resume)
        try:
            # Embedding-based scoring is always computed (deterministic contract).
            result = await asyncio.to_thread(self._embedding_score, job_description, resume)
            result["blinded"] = True  # protected attributes removed before scoring

            # Second node: cross-validate the résumé's timeline for data-integrity
            # anomalies (advisory). Flags never change the score — they only ask a
            # human to verify. Runs on the *raw* text because blinding scrubs years
            # (an age-proxy guard) which the timeline check needs; only the flag
            # *count* is persisted to the audit/case, never the raw years.
            analysis = await resume_resolver.analyze(raw_resume)
            flags = analysis["flags"]
            result["consistency_flags"] = flags
            if flags:
                result["needs_review"] = True
                result["reasoning"] += (
                    f" ⚠ {len(flags)} timeline consistency flag(s) for human review "
                    "(advisory — does not affect the score)."
                )

            # If CrewAI is available, enrich the reasoning with its narrative.
            crew = self._build_crew(job_description, resume)
            if crew is not None:
                try:
                    crew_output = await asyncio.to_thread(crew.kickoff)
                    result["reasoning"] = (
                        f"{result['reasoning']} CrewAI review: {str(crew_output)[:600]}"
                    )
                except Exception as exc:  # noqa: BLE001
                    result["reasoning"] += f" (CrewAI unavailable: {exc})"

            # Land the screen in the Cases ledger as a SCREENING case so it shows
            # up in the Cases panel (every agent action → Cases + Audit). The
            # screen itself is complete → "resolved"; the recruiter acts on it.
            case = await memory.create_case(
                category="SCREENING",
                summary=f"Resume screen → {result['recommendation']} (score {result['score']})",
                detail=result.get("reasoning", "")[:500],
                assigned_agent="recruiter",
                status="resolved",
            )
            result["case_id"] = case["id"]

            await memory.log_audit(
                AGENT_NAME,
                "resume_screen",
                {"jd_len": len(job_description), "resume_len": len(resume)},
                {
                    "score": result["score"],
                    "recommendation": result["recommendation"],
                    "case_id": case["id"],
                    "consistency_flags": len(result.get("consistency_flags", [])),
                },
                "success",
            )
            await memory.upsert_agent(
                AGENT_NAME,
                status="idle",
                last_action=f"screened resume → {result['recommendation']}",
                increment_runs=True,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            await memory.log_audit(AGENT_NAME, "resume_screen", {"error": str(exc)}, {}, "error")
            await memory.upsert_agent(AGENT_NAME, status="error", last_action=str(exc))
            raise


resume_screener_agent = ResumeScreenerAgent()
