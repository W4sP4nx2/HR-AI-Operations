"""AI safety guardrails: prompt-injection detection and demographic blinding.

These implement the compliance-critical behaviours auditors test for:

  * **Prompt-injection defense** — refuse + log attempts to override instructions
    ("ignore previous instructions", "reveal the system prompt", etc.).
  * **Demographic blinding** — strip protected attributes (name header, age /
    graduation year, pregnancy / maternity, gender, race, marital status) from a
    resume *before scoring*, so the score is name- and demographic-invariant
    (Title VII / ADEA / PDA / EEOC fair-hiring).

Both are deterministic, dependency-free, and cheap enough to run on every call.
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Prompt-injection detection
# --------------------------------------------------------------------------- #

_INJECTION_PATTERNS = [
    r"ignore\s+all\s+(previous|prior|above)\s+(instructions|rules|policy|prompts?)",
    r"ignore (all|any|the|previous|prior|above)\s+(instructions|rules|policy|prompts?)",
    r"disregard (all|the|previous|prior|above)",
    r"forget (all|everything|the above|previous)",
    r"reveal (the )?(system )?prompt",
    r"(show|print|repeat) (me )?(your |the )?(system )?(prompt|instructions)",
    r"you are now\b",
    r"act as (if you are )?(an? )?(admin|root|developer|dan)\b",
    r"override (the )?(policy|rules|guardrails|safety)",
    r"approve (this|it|everything) (regardless|anyway|no matter)",
    r"bypass (the )?(approval|policy|rules|guardrails)",
    r"jailbreak",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

REFUSAL_MESSAGE = (
    "I can't act on instructions that try to override HR policy or my safeguards. "
    "This attempt has been logged. If you have a legitimate request, please rephrase it."
)


def detect_prompt_injection(text: str) -> bool:
    """Return True if ``text`` looks like a prompt-injection / jailbreak attempt."""
    if not text:
        return False
    return bool(_INJECTION_RE.search(text))


# --------------------------------------------------------------------------- #
# Demographic blinding (resume screening)
# --------------------------------------------------------------------------- #

# Lines whose label reveals a protected attribute are dropped entirely.
_PROTECTED_LABEL = re.compile(
    r"^\s*(name|full name|gender|sex|age|dob|date of birth|nationality|"
    r"race|ethnicity|religion|marital status|pronouns?|photo)\s*[:\-=]",
    re.IGNORECASE,
)

# Protected-attribute phrases removed inline anywhere they appear.
_PROTECTED_TERMS = re.compile(
    r"\b(pregnan\w*|maternity|paternity|parental leave|disabilit\w*|veteran|"
    r"married|single|divorced|widowed)\b",
    re.IGNORECASE,
)

# Standalone 4-digit years (graduation dates → age proxy) are masked.
_YEAR = re.compile(r"\b(19|20)\d{2}\b")


def _strip_protected_label_line(line: str) -> str | None:
    """Remove a leading protected label while preserving later resume content."""
    match = _PROTECTED_LABEL.match(line)
    if not match:
        return line
    remainder = line[match.end() :].strip()
    # Common pasted resumes can arrive as one line:
    # "Name: Jane Doe. Backend engineer with Python..."
    # Drop the labelled value, then keep the non-sensitive sentence that follows.
    for separator in (". ", "; ", " | "):
        if separator in remainder:
            return remainder.split(separator, 1)[1].strip()
    return None


def blind_demographics(text: str) -> str:
    """Remove protected attributes from resume text before scoring.

    Drops labelled lines (Name:/Gender:/DOB: …), masks protected-attribute phrases
    and standalone years, so two resumes that differ only by a candidate's name or
    demographic markers produce the same score.
    """
    if not text:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        # Drop entire lines that reveal a protected attribute — both labelled
        # headers (Name:/DOB:) and free-text mentions (maternity/pregnancy).
        # When a pasted resume has useful non-sensitive content after the labelled
        # value on the same line, keep only the later sentence.
        stripped = _strip_protected_label_line(line)
        if stripped is None or _PROTECTED_TERMS.search(stripped):
            continue
        line = _YEAR.sub("[year]", stripped)
        kept.append(line)
    return "\n".join(kept)
