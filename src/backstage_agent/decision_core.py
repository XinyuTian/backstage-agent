from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class DecisionBucket(str, Enum):
    AUTO_APPLY_DRAFT = "auto_apply_draft"
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_MY_PREFERENCE = "needs_my_preference"
    REJECT = "reject"
    DATA_PARSE_ERROR = "data_parse_error"


@dataclass(frozen=True)
class ScreeningRules:
    bucket_labels: dict[str, str]
    career_value: dict[str, int]
    preferences: dict[str, dict[str, str]]
    reviewer_downgrade_order: list[str]


@dataclass(frozen=True)
class StructuredScreening:
    suggested_bucket: DecisionBucket
    role_type: str
    project_type: str
    career_value_score: int
    required_preferences: list[str]
    missing_preference_keys: list[str]
    pay_burden: str
    travel_burden: str
    time_burden: str
    fit_reasons: list[str]
    concerns: list[str]
    evidence_snippets: list[str]
    confidence: float
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StructuredScreening":
        required = {
            "suggested_bucket",
            "role_type",
            "project_type",
            "career_value_score",
            "required_preferences",
            "missing_preference_keys",
            "pay_burden",
            "travel_burden",
            "time_burden",
            "fit_reasons",
            "concerns",
            "evidence_snippets",
            "confidence",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(
                "missing required structured screening fields: " + ", ".join(missing)
            )
        score = _int_in_range(data["career_value_score"], 0, 5, "career_value_score")
        confidence = _float_in_range(data["confidence"], 0, 1, "confidence")
        return cls(
            suggested_bucket=DecisionBucket(str(data["suggested_bucket"])),
            role_type=str(data["role_type"]),
            project_type=str(data["project_type"]),
            career_value_score=score,
            required_preferences=_string_list(data["required_preferences"], "required_preferences"),
            missing_preference_keys=_string_list(
                data["missing_preference_keys"], "missing_preference_keys"
            ),
            pay_burden=str(data["pay_burden"]),
            travel_burden=str(data["travel_burden"]),
            time_burden=str(data["time_burden"]),
            fit_reasons=_string_list(data["fit_reasons"], "fit_reasons"),
            concerns=_string_list(data["concerns"], "concerns"),
            evidence_snippets=_string_list(data["evidence_snippets"], "evidence_snippets"),
            confidence=confidence,
            raw=dict(data),
        )


@dataclass(frozen=True)
class StructuredReview:
    verdict: str
    downgrade_to: DecisionBucket | None
    evidence_snippets: list[str]
    reasons: list[str]
    concerns: list[str]
    confidence: float
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StructuredReview":
        required = {
            "verdict",
            "downgrade_to",
            "evidence_snippets",
            "reasons",
            "concerns",
            "confidence",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError("missing required structured review fields: " + ", ".join(missing))
        verdict = str(data["verdict"]).strip().lower()
        if verdict not in {"confirm", "downgrade"}:
            raise ValueError("verdict must be confirm or downgrade")
        downgrade_value = data["downgrade_to"]
        downgrade_to = (
            DecisionBucket(str(downgrade_value))
            if downgrade_value not in {None, "", "null"}
            else None
        )
        return cls(
            verdict=verdict,
            downgrade_to=downgrade_to,
            evidence_snippets=_string_list(data["evidence_snippets"], "evidence_snippets"),
            reasons=_string_list(data["reasons"], "reasons"),
            concerns=_string_list(data["concerns"], "concerns"),
            confidence=_float_in_range(data["confidence"], 0, 1, "confidence"),
            raw=dict(data),
        )


@dataclass(frozen=True)
class DecisionArtifacts:
    final_bucket: DecisionBucket
    classifier_json: dict[str, Any] | None = None
    reviewer_json: dict[str, Any] | None = None
    reviewer_impact: str = "not_reviewed"
    schema_error: str = ""


def load_screening_rules(path: Path | str = "screening_rules.json") -> ScreeningRules:
    rules_path = Path(path)
    data = json.loads(rules_path.read_text(encoding="utf-8"))
    return ScreeningRules(
        bucket_labels={str(key): str(value) for key, value in data["bucket_labels"].items()},
        career_value={
            str(key): _int_in_range(value, 0, 5, f"career_value.{key}")
            for key, value in data["career_value"].items()
        },
        preferences={
            str(key): {str(item_key): str(item_value) for item_key, item_value in value.items()}
            for key, value in data["preferences"].items()
        },
        reviewer_downgrade_order=[
            str(value) for value in data.get("reviewer_downgrade_order", [])
        ],
    )


def resolve_final_bucket(
    screening: StructuredScreening | None = None,
    review: StructuredReview | None = None,
    schema_error: str = "",
    base_bucket: DecisionBucket | None = None,
) -> DecisionArtifacts:
    if schema_error:
        return DecisionArtifacts(
            final_bucket=DecisionBucket.DATA_PARSE_ERROR,
            classifier_json=screening.raw if screening else None,
            reviewer_json=review.raw if review else None,
            reviewer_impact="schema_error",
            schema_error=schema_error,
        )
    bucket = base_bucket or (screening.suggested_bucket if screening else DecisionBucket.DATA_PARSE_ERROR)
    classifier_json = screening.raw if screening else None
    reviewer_json = review.raw if review else None
    if screening and screening.missing_preference_keys:
        return DecisionArtifacts(
            final_bucket=DecisionBucket.NEEDS_MY_PREFERENCE,
            classifier_json=classifier_json,
            reviewer_json=reviewer_json,
            reviewer_impact="not_reviewed" if review is None else "base_needs_preference",
        )
    if review is None:
        return DecisionArtifacts(
            final_bucket=bucket,
            classifier_json=classifier_json,
            reviewer_impact="not_reviewed",
        )
    if review.verdict == "confirm" or review.downgrade_to is None:
        return DecisionArtifacts(
            final_bucket=bucket,
            classifier_json=classifier_json,
            reviewer_json=reviewer_json,
            reviewer_impact="confirmed",
        )
    if not review.evidence_snippets:
        return DecisionArtifacts(
            final_bucket=bucket,
            classifier_json=classifier_json,
            reviewer_json=reviewer_json,
            reviewer_impact="ignored_no_evidence",
        )
    if _allowed_reviewer_downgrade(bucket, review.downgrade_to):
        return DecisionArtifacts(
            final_bucket=review.downgrade_to,
            classifier_json=classifier_json,
            reviewer_json=reviewer_json,
            reviewer_impact="downgraded",
        )
    return DecisionArtifacts(
        final_bucket=bucket,
        classifier_json=classifier_json,
        reviewer_json=reviewer_json,
        reviewer_impact="ignored_policy",
    )


def should_review_bucket(bucket: str | DecisionBucket | None) -> bool:
    return _bucket(bucket) is DecisionBucket.AUTO_APPLY_DRAFT


def should_draft_bucket(bucket: str | DecisionBucket | None) -> bool:
    return _bucket(bucket) is DecisionBucket.AUTO_APPLY_DRAFT


def label_for_bucket(bucket: str | DecisionBucket | None) -> str:
    labels = {
        DecisionBucket.AUTO_APPLY_DRAFT: "Auto Apply/Draft",
        DecisionBucket.READY_FOR_REVIEW: "Ready For Review",
        DecisionBucket.NEEDS_MY_PREFERENCE: "Needs My Preference",
        DecisionBucket.REJECT: "Reject",
        DecisionBucket.DATA_PARSE_ERROR: "Data/Parse Error",
    }
    return labels.get(_bucket(bucket), "Unknown")


def _allowed_reviewer_downgrade(current: DecisionBucket, target: DecisionBucket) -> bool:
    if current is DecisionBucket.AUTO_APPLY_DRAFT:
        return target is DecisionBucket.READY_FOR_REVIEW
    if current is DecisionBucket.READY_FOR_REVIEW:
        return target in {DecisionBucket.NEEDS_MY_PREFERENCE, DecisionBucket.REJECT}
    return False


def _bucket(value: str | DecisionBucket | None) -> DecisionBucket | None:
    if value is None:
        return None
    if isinstance(value, DecisionBucket):
        return value
    try:
        return DecisionBucket(str(value))
    except ValueError:
        return None


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [str(item) for item in value]


def _int_in_range(value: Any, low: int, high: int, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number < low or number > high:
        raise ValueError(f"{field_name} must be between {low} and {high}")
    return number


def _float_in_range(value: Any, low: float, high: float, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if number < low or number > high:
        raise ValueError(f"{field_name} must be between {low:g} and {high:g}")
    return number
