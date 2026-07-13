"""Mock Fireworks JSON-mode responses for zero-cost certification proof."""

VALID_TRIAGE_RESPONSE = {
    "category": "BENEFITS",
    "priority": "MEDIUM",
    "confidence": 0.92,
    "rationale": "Employee asked about dental coverage",
}

INVALID_TRIAGE_RESPONSE = {
    "category": "BENEFITS",
    "confidence": 0.85,
}

PII_CONTAMINATED_RESPONSE = {
    "category": "COMPLIANCE",
    "priority": "HIGH",
    "confidence": 0.95,
    "rationale": "SSN 123-45-6789 found in complaint",
}

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["BENEFITS", "POLICY", "ONBOARDING", "PERFORMANCE", "COMPLIANCE", "URGENT"],
        },
        "priority": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "rationale": {"type": "string"},
    },
    "required": ["category", "priority", "confidence", "rationale"],
    "additionalProperties": False,
}
