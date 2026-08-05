from __future__ import annotations

import re

from .candidate_models import CandidateFeatures, RequirementMatch, RequirementStatus
from .models import ActorProfile


_ANY_GENDER_VALUES = {
    "all",
    "all genders",
    "any",
    "any gender",
    "any genders",
    "open",
    "open to all genders",
    "open to any gender",
}


def match_requirements(
    features: CandidateFeatures,
    profile: ActorProfile,
    rules: dict,
) -> list[RequirementMatch]:
    known = rules.get("known_requirements", {})
    matches: list[RequirementMatch] = []
    for key, raw_requirement in features.requirements.items():
        if _requirement_is_empty(raw_requirement):
            continue
        requirement = _requirement_dict(raw_requirement)
        semantic_key = _semantic_requirement_key(key, requirement)
        certainty = str(requirement.get("certainty") or "explicit").strip().lower()
        if certainty == "inferred":
            matches.append(
                RequirementMatch(
                    requirement_key=semantic_key,
                    status=RequirementStatus.NOT_APPLICABLE,
                    required=False,
                    local_value="",
                    evidence=str(requirement.get("evidence") or ""),
                    reason="Inferred requirement is shown for review but not scored.",
                    score_impact=0,
                )
            )
            continue
        if semantic_key == "gender":
            status, local_value = _evaluate_gender_requirement(profile, requirement)
            evidence = str(requirement.get("evidence") or "")
            matches.append(
                RequirementMatch(
                    requirement_key="gender",
                    status=status,
                    required=bool(requirement.get("required", True)),
                    local_value=local_value,
                    evidence=evidence or _gender_requirement_text(requirement),
                    reason=_reason_for_status(status),
                    score_impact=0,
                )
            )
            continue
        required = bool(requirement.get("required"))
        evidence = str(requirement.get("evidence") or "")
        rule = known.get(semantic_key)
        if not rule:
            matches.append(
                RequirementMatch(
                    requirement_key=key,
                    status=RequirementStatus.UNKNOWN_NEEDS_USER_INPUT,
                    required=required,
                    local_value="",
                    evidence=evidence,
                    reason="No local rule exists for this extracted requirement.",
                    score_impact=0,
                )
            )
            continue
        status, local_value = _evaluate_rule(profile, rule)
        points = int(rule.get("points_when_met", 0)) if status is RequirementStatus.MET else 0
        matches.append(
            RequirementMatch(
                requirement_key=key,
                status=status,
                required=required,
                local_value=local_value,
                evidence=evidence,
                reason=_reason_for_status(status),
                score_impact=points,
            )
        )
    return matches


def _semantic_requirement_key(key: str, requirement: dict) -> str:
    normalized_key = key.strip().lower()
    if normalized_key == "gender" or re.match(
        r"^gender_(?:female|male|non[-_]?binary|open|any|all)$", normalized_key
    ):
        return "gender"
    if str(requirement.get("type") or "").strip().lower() == "gender":
        return "gender"
    label = str(requirement.get("requirement") or "").strip().lower()
    return "gender" if re.match(r"^gender\s*:", label) else key


def _gender_requirement_text(requirement: dict) -> str:
    for field in ("value", "requirement", "evidence"):
        value = str(requirement.get(field) or "").strip()
        if value:
            return value
    return ""


def _normalize_gender_values(value: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    if normalized in _ANY_GENDER_VALUES:
        return {"any"}
    if normalized.startswith("gender:"):
        normalized = normalized.split(":", 1)[1].strip()
    values = set()
    if re.search(r"\bfemale\b|\bwoman\b|\bwomen\b", normalized):
        values.add("female")
    without_female = re.sub(r"\bfemale\b", "", normalized)
    if re.search(r"\bmale\b|\bman\b|\bmen\b", without_female):
        values.add("male")
    if re.search(r"\bnon[- ]?binary\b", normalized):
        values.add("nonbinary")
    return values


def _evaluate_gender_requirement(
    profile: ActorProfile, requirement: dict
) -> tuple[RequirementStatus, str]:
    local = {
        value
        for gender in profile.genders
        for value in _normalize_gender_values(str(gender))
    }
    local_text = ", ".join(str(gender) for gender in profile.genders)
    required = _normalize_gender_values(_gender_requirement_text(requirement))
    if "any" in required:
        return RequirementStatus.MET, local_text
    if not required or not local:
        return RequirementStatus.UNKNOWN_NEEDS_USER_INPUT, local_text
    status = RequirementStatus.MET if required & local else RequirementStatus.NOT_MET
    return status, local_text


def _requirement_is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple)):
        return not value or all(_requirement_is_empty(item) for item in value)
    if isinstance(value, dict):
        substantive_value = value.get("value")
        if (
            isinstance(substantive_value, str)
            and substantive_value.strip().lower() == "not specified"
            and _requirement_is_empty(value.get("evidence"))
        ):
            other_substantive_values = [
                item
                for key, item in value.items()
                if key not in {"required", "optional", "type", "value", "evidence"}
            ]
            return all(
                _requirement_is_empty(item)
                or (
                    isinstance(item, str)
                    and item.strip().lower() == "not specified"
                )
                for item in other_substantive_values
            )
        meaningful = [
            item
            for key, item in value.items()
            if key not in {"required", "optional"}
        ]
        return not meaningful or all(_requirement_is_empty(item) for item in meaningful)
    return False


def _requirement_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return {"required": True, "evidence": value}
    if isinstance(value, list):
        return {
            "required": True,
            "evidence": "; ".join(str(item) for item in value if str(item).strip()),
        }
    return {"required": True, "evidence": str(value)}


def _evaluate_rule(profile: ActorProfile, rule: dict) -> tuple[RequirementStatus, str]:
    if "profile_attribute" in rule:
        attr = str(rule["profile_attribute"])
        value = _resolve_profile_attribute(profile, attr)
        local_value = _stringify_value(value)
        if _value_matches(value, rule.get("met_values", [])):
            return RequirementStatus.MET, local_value
        return RequirementStatus.NOT_MET, local_value
    if "profile_list" in rule:
        values = getattr(profile, str(rule["profile_list"]), [])
        joined = ", ".join(str(value) for value in values)
        if any(_value_matches(value, rule.get("met_values", [])) for value in values):
            return RequirementStatus.MET, joined
        return RequirementStatus.NOT_MET, joined
    return RequirementStatus.UNKNOWN_NEEDS_USER_INPUT, ""


def _resolve_profile_attribute(profile: ActorProfile, attr: str) -> str | int | None:
    if attr in profile.attributes:
        return profile.attributes[attr]
    return getattr(profile, attr, "")


def _stringify_value(value: str | int | None) -> str:
    return "" if value in ("", None) else str(value)


def _value_matches(value: str, allowed: list[str]) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {str(item).strip().lower() for item in allowed}


def _reason_for_status(status: RequirementStatus) -> str:
    if status is RequirementStatus.MET:
        return "Stored actor profile satisfies this requirement."
    if status is RequirementStatus.NOT_MET:
        return "Stored actor profile does not satisfy this requirement."
    return "Requirement needs a local fact or user preference."
