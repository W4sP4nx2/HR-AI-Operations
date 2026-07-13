"""Resume Screener agent built with CrewAI.

A crew of three role-specialised agents:
    * JD Parser Agent       — extracts required skills from the job description.
    * Resume Scorer Agent   — scores the resume 0-100 against JD requirements.
    * Recommendation Agent  — writes an advisory fit summary for human review.

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
from models.naive_baselines import resume_overlap_baseline

AGENT_NAME = "resume_screener_agent"
STRONG_FIT = "strong_fit"
REVIEW_RECOMMENDED = "review_recommended"

_SKILL_AUDIT_HANDOFF_OBJECTIVES: dict[str, Any] = {
    "schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "skill": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["demonstrated", "aspirational", "negated", "absent"],
                        },
                    },
                    "required": ["skill", "status"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    },
    "require_pii_free": True,
}

_CREWAI_NARRATIVE_OBJECTIVES: dict[str, Any] = {
    "schema": {
        "type": "object",
        "properties": {"narrative": {"type": "string", "maxLength": 800}},
        "required": ["narrative"],
        "additionalProperties": False,
    },
    "require_pii_free": True,
}

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


def advisory_fit_label(score: int) -> str:
    """Return an advisory fit label, not a hiring decision."""
    return STRONG_FIT if score >= 65 else REVIEW_RECOMMENDED


class ResumeScreenerAgent:
    """Screens resumes against a job description for human decision support."""

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
        from core.runtime_key import llm_provider

        if llm_provider() != "anthropic" or not settings.anthropic_api_key:
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
                goal="Write an advisory candidate-role fit summary with clear evidence.",
                backstory="A reviewer who writes concise, fair decision-support notes.",
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
                description="Write an advisory fit summary with evidence and review notes.",
                expected_output="A short decision-support paragraph.",
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
        resume_terms = _extract_skill_terms(resume)
        overlap = resume_overlap_baseline.predict(jd_skills, resume_terms)
        matched = list(overlap.matched_skills)
        missing = list(overlap.missing_skills)

        # Input guard: a one-word "resume" (e.g. "john") or an empty JD is not a
        # valid assessment — flag for review instead of returning a confident score.
        resume_tokens = len(resume.split())
        jd_tokens = len(jd.split())
        insufficient = resume_tokens < 8 or jd_tokens < 3
        if insufficient:
            return {
                "score": 0,
                "recommendation": REVIEW_RECOMMENDED,
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
        keyword_ratio = overlap.score
        # Round half-up everywhere (matches JS Math.round) so the gauge, the
        # coverage % and the matched/total counts are all mutually consistent —
        # no banker's-rounding drift (e.g. 10/16 = 62.5% shows as 63%, not 62%).
        score = int(100 * (0.6 * semantic + 0.4 * keyword_ratio) + 0.5)
        coverage = int(keyword_ratio * 100 + 0.5)

        recommendation = advisory_fit_label(score)
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
            # Private — carried so the (optional) skill-audit pass can re-score on
            # demonstrated skills only; popped before the result is returned.
            "_semantic": semantic,
            "_total": total,
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

            # Negation pass (opt-in, LLM-gated): grade each MATCHED skill's context
            # and drop keyword matches that are negated/aspirational, then re-score.
            # In-request (BYOK-safe). When no live key, it returns None and we keep
            # the keyword result but mark the mode so the UI downgrades confidence —
            # it must never present an unvalidated score as validated.
            from agents.skill_validator import SkillAudit, apply_audit, skill_validator
            from core.a2a_envelope import certified_handoff

            async def _validate_skills(payload: dict[str, Any]) -> dict[str, Any]:
                audit_result = await skill_validator.validate(
                    list(payload.get("skills", [])),
                    str(payload.get("resume", "")),
                )
                # A gated or unavailable validator is an explicit empty audit,
                # not a failed inter-agent handoff.  The caller below preserves
                # the visible ``keyword_fallback`` mode when no evidence items
                # are available, while the A2A envelope remains schema-valid.
                return audit_result.model_dump() if audit_result is not None else {"items": []}

            envelope = await certified_handoff(
                source_agent=AGENT_NAME,
                target_agent="skill_validator",
                func=_validate_skills,
                payload={"skills": result.get("matched_skills", []), "resume": resume},
                objectives=_SKILL_AUDIT_HANDOFF_OBJECTIVES,
            )
            if envelope.certification.is_valid and envelope.payload.get("items"):
                result = apply_audit(result, SkillAudit.model_validate(envelope.payload))
            else:
                result["skill_audit_mode"] = "keyword_fallback"
                result.setdefault("unverified_skills", [])
            result.pop("_semantic", None)
            result.pop("_total", None)

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
                    from agents.crewai_adapter import run_certified_crewai_task

                    async def _kickoff(_payload: dict[str, Any]) -> dict[str, str]:
                        output = await asyncio.to_thread(crew.kickoff)
                        return {"narrative": str(output)}

                    envelope = await run_certified_crewai_task(
                        task_name="resume_narrative",
                        crew_input={"job_description": job_description, "resume": resume},
                        executor=_kickoff,
                        objectives=_CREWAI_NARRATIVE_OBJECTIVES,
                        source_agent=AGENT_NAME,
                        target_agent="human_reviewer",
                    )
                    if envelope.certification.is_valid:
                        narrative = str(envelope.payload.get("narrative", ""))[:800]
                        result["reasoning"] = f"{result['reasoning']} CrewAI review: {narrative}"
                        result["crewai_mode"] = "certified_narrative"
                    else:
                        result["crewai_mode"] = "certification_failed"
                except Exception:  # noqa: BLE001
                    result["crewai_mode"] = "unavailable"

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
