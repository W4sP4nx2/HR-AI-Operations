"""Certification guardrails for Fireworks-generated HR outputs.

This module performs no network I/O and does not construct model clients. It is
intended to sit after Fireworks generation, A2A delegation, or batch processing
and answer one question: is this output safe and objective-valid enough for the
next agent or human workflow step?
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from core.safety import _regex_redact, redact_pii

_OBFUSCATED_SSN = re.compile(
    r"\bssn\s*[:\-]?\s*"
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine)"
    r"(?:[\s\-]+(?:zero|one|two|three|four|five|six|seven|eight|nine)){8}\b",
    re.IGNORECASE,
)


class CertifiedResult(BaseModel):
    """Result of validating one LLM response against explicit objectives."""

    is_valid: bool
    cleaned_output: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    violations: list[str] = Field(default_factory=list)
    redaction_count: int = Field(default=0, ge=0)


class FireworksOutputCertifier:
    """Validate Fireworks outputs before they enter HR agent workflows.

    Supported objective keys:
      * ``schema`` or ``json_schema``: JSON schema-like dict for the response.
      * ``min_confidence``: minimum accepted confidence, default ``0.0``.
      * ``require_pii_free``: require original output to contain no PII, default
        ``True``.
      * ``confidence_field``: preferred confidence field name, default searches
        common names such as ``confidence`` and ``confidence_score``.
      * ``required_fields``: top-level fields that must be present.
      * ``forbidden_fields``: top-level fields that must be absent.
      * ``required_substrings``: strings that must appear in the response text.

    The JSON-schema support is deliberately practical rather than exhaustive:
    object properties, required fields, arrays, enum, primitive types, nullable
    ``type`` lists, and common numeric/string/list constraints are enforced via
    Pydantic. Unsupported shapes degrade to ``Any`` instead of guessing.
    """

    _CONFIDENCE_FIELDS = (
        "confidence",
        "confidence_score",
        "score_confidence",
        "certainty",
        "probability",
    )

    def validate_json_schema(self, response: str, schema: dict[str, Any]) -> bool:
        """Return whether a JSON response validates against ``schema``."""
        try:
            self._validate_json_schema(response, schema)
        except (TypeError, ValueError, json.JSONDecodeError, ValidationError):
            return False
        return True

    def check_pii_free(self, text: str) -> bool:
        """Return whether existing redaction logic finds no PII in ``text``."""
        return self._redact_for_certification(text) == text

    def extract_confidence(self, response: dict[str, Any]) -> float:
        """Extract a bounded confidence value from common response shapes."""
        value = self._find_confidence(response)
        if value is None:
            return 0.0
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            return 0.0

        if confidence > 1.0 and confidence <= 100.0:
            confidence = confidence / 100.0
        return min(1.0, max(0.0, confidence))

    def certify(
        self, response: str, objectives: dict[str, Any]
    ) -> CertifiedResult | ValidationError:
        """Certify ``response`` against strict objectives.

        Schema validation failures are returned as the original Pydantic
        ``ValidationError`` so callers can inspect exact field failures. Other
        objective failures return ``CertifiedResult(is_valid=False, ...)`` with
        named violations.
        """
        schema = self._objective_schema(objectives)
        try:
            payload = (
                self._validate_json_schema(response, schema)
                if schema
                else self._parse_json(response)
            )
        except ValidationError as exc:
            return exc
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            cleaned = self._redact_for_certification(response)
            return CertifiedResult(
                is_valid=False,
                cleaned_output=cleaned,
                confidence=0.0,
                violations=[f"invalid_json: {exc}"],
                redaction_count=self._redaction_count(response, cleaned),
            )

        violations: list[str] = []
        if objectives.get("require_pii_free", True) and not self.check_pii_free(response):
            violations.append("pii_detected")

        if isinstance(payload, dict):
            confidence = self._extract_confidence_for_objectives(payload, objectives)
            violations.extend(self._check_field_objectives(payload, objectives))
        else:
            confidence = 0.0

        min_confidence = self._objective_float(objectives, "min_confidence", default=0.0)
        if confidence < min_confidence:
            violations.append(f"confidence_below_minimum:{confidence:.3f}<{min_confidence:.3f}")

        required_substrings = objectives.get("required_substrings", [])
        if isinstance(required_substrings, list):
            for substring in required_substrings:
                if isinstance(substring, str) and substring not in response:
                    violations.append(f"missing_substring:{substring}")
        else:
            violations.append("required_substrings_must_be_list")

        redacted_payload = self._redact_payload(payload)
        cleaned = json.dumps(redacted_payload, sort_keys=True)
        return CertifiedResult(
            is_valid=not violations,
            cleaned_output=cleaned,
            confidence=confidence,
            violations=violations,
            redaction_count=self._redaction_count(payload, redacted_payload),
        )

    def _validate_json_schema(self, response: str, schema: Mapping[str, Any]) -> Any:
        if not isinstance(schema, Mapping):
            raise TypeError("schema must be a mapping")
        parsed = self._parse_json(response)
        model = self._model_from_schema("FireworksCertifiedPayload", schema)
        return model.model_validate(parsed).model_dump()

    def _parse_json(self, response: str) -> Any:
        if not isinstance(response, str):
            raise TypeError("response must be a string")
        return json.loads(response)

    def _objective_schema(self, objectives: Mapping[str, Any]) -> dict[str, Any] | None:
        schema = objectives.get("schema", objectives.get("json_schema"))
        if schema is None:
            return None
        if not isinstance(schema, dict):
            raise TypeError("objectives schema must be a dict")
        return schema

    def _extract_confidence_for_objectives(
        self, response: dict[str, Any], objectives: Mapping[str, Any]
    ) -> float:
        confidence_field = objectives.get("confidence_field")
        if isinstance(confidence_field, str) and confidence_field:
            return self.extract_confidence({confidence_field: response.get(confidence_field)})
        return self.extract_confidence(response)

    def _find_confidence(self, value: Any) -> Any:
        if isinstance(value, Mapping):
            for field in self._CONFIDENCE_FIELDS:
                if field in value:
                    return value[field]
            for nested in value.values():
                found = self._find_confidence(nested)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._find_confidence(item)
                if found is not None:
                    return found
        return None

    def _check_field_objectives(
        self, payload: Mapping[str, Any], objectives: Mapping[str, Any]
    ) -> list[str]:
        violations: list[str] = []
        required_fields = objectives.get("required_fields", [])
        forbidden_fields = objectives.get("forbidden_fields", [])

        if isinstance(required_fields, list):
            for field in required_fields:
                if isinstance(field, str) and field not in payload:
                    violations.append(f"missing_field:{field}")
        else:
            violations.append("required_fields_must_be_list")

        if isinstance(forbidden_fields, list):
            for field in forbidden_fields:
                if isinstance(field, str) and field in payload:
                    violations.append(f"forbidden_field:{field}")
        else:
            violations.append("forbidden_fields_must_be_list")

        return violations

    def _redact_payload(self, payload: Any) -> Any:
        if isinstance(payload, str):
            return self._redact_for_certification(payload)
        if isinstance(payload, Mapping):
            return {key: self._redact_payload(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._redact_payload(value) for value in payload]
        return payload

    def _redact_for_certification(self, text: str) -> str:
        redacted = redact_pii(text)
        redacted = _OBFUSCATED_SSN.sub("[redacted-obfuscated-ssn]", redacted)
        if redacted != text:
            return redacted
        return _regex_redact(text)

    def _redaction_count(self, original: Any, redacted: Any) -> int:
        if isinstance(original, str) and isinstance(redacted, str):
            return int(original != redacted)
        if isinstance(original, Mapping) and isinstance(redacted, Mapping):
            total = 0
            for key, value in original.items():
                total += self._redaction_count(value, redacted.get(key))
            return total
        if isinstance(original, list) and isinstance(redacted, list):
            return sum(
                self._redaction_count(before, after)
                for before, after in zip(original, redacted, strict=False)
            )
        return 0

    def _objective_float(self, objectives: Mapping[str, Any], key: str, *, default: float) -> float:
        value = objectives.get(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _model_from_schema(self, name: str, schema: Mapping[str, Any]) -> type[BaseModel]:
        schema_type = schema.get("type", "object")
        if schema_type != "object":
            raise ValueError("top-level schema must be an object")

        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            raise ValueError("schema properties must be a mapping")

        required = set(schema.get("required", []))
        if not all(isinstance(field, str) for field in required):
            raise ValueError("schema required must be a list of field names")

        fields: dict[str, tuple[Any, Any]] = {}
        for field_name, field_schema in properties.items():
            if not isinstance(field_name, str) or not isinstance(field_schema, Mapping):
                raise ValueError("schema properties must map strings to schemas")
            annotation = self._annotation_from_schema(f"{name}_{field_name}", field_schema)
            default: Any = ... if field_name in required else None
            fields[field_name] = (annotation, Field(default, **self._field_kwargs(field_schema)))

        extra = "forbid" if schema.get("additionalProperties") is False else "ignore"
        return create_model(name, __config__=ConfigDict(extra=extra), **fields)

    def _annotation_from_schema(self, name: str, schema: Mapping[str, Any]) -> Any:
        if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
            return Literal.__getitem__(tuple(schema["enum"]))

        schema_type = schema.get("type")
        if isinstance(schema_type, list):
            non_null = [item for item in schema_type if item != "null"]
            if len(non_null) == 1 and len(non_null) != len(schema_type):
                return (
                    self._annotation_from_schema(name, {**dict(schema), "type": non_null[0]}) | None
                )
            if len(non_null) > 1:
                annotation: Any = self._annotation_from_schema(
                    name, {**dict(schema), "type": non_null[0]}
                )
                for item in non_null[1:]:
                    annotation = annotation | self._annotation_from_schema(
                        name, {**dict(schema), "type": item}
                    )
                return annotation | None if len(non_null) != len(schema_type) else annotation
            return Any

        if schema_type == "string":
            return str
        if schema_type == "integer":
            return int
        if schema_type == "number":
            return float
        if schema_type == "boolean":
            return bool
        if schema_type == "array":
            items = schema.get("items", {})
            item_type = (
                self._annotation_from_schema(f"{name}Item", items)
                if isinstance(items, Mapping)
                else Any
            )
            return list[item_type]
        if schema_type == "object":
            properties = schema.get("properties")
            if isinstance(properties, Mapping):
                return self._model_from_schema(name, schema)
            return dict[str, Any]
        return Any

    def _field_kwargs(self, schema: Mapping[str, Any]) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        mapping = {
            "description": "description",
            "minimum": "ge",
            "maximum": "le",
            "exclusiveMinimum": "gt",
            "exclusiveMaximum": "lt",
            "minLength": "min_length",
            "maxLength": "max_length",
            "minItems": "min_length",
            "maxItems": "max_length",
        }
        for source, target in mapping.items():
            if source in schema:
                kwargs[target] = schema[source]
        return kwargs
