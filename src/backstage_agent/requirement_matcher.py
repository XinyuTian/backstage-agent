from __future__ import annotations

from .candidate_models import CandidateFeatures, RequirementMatch, RequirementStatus
from .models import ActorProfile


def match_requirements(
    features: CandidateFeatures,
    profile: ActorProfile,
    rules: dict,
) -> list[RequirementMatch]:
    known = rules.get("known_requirements", {})
    matches: list[RequirementMatch] = []
    for key, raw_requirement in features.requirements.items():
        requirement = _requirement_dict(raw_requirement)
        required = bool(requirement.get("required"))
        evidence = str(requirement.get("evidence") or "")
        rule = known.get(key)
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
