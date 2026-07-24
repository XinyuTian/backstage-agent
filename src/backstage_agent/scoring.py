from __future__ import annotations

import json
from dataclasses import replace
from importlib import resources
from pathlib import Path

from .candidate_models import (
    CandidateFeatures,
    CandidateScore,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)

_NO_REQUIREMENTS_BASELINE_FRACTION = 0.5
_OPTIONAL_ONLY_BONUS_FRACTION = 0.3
_REQUIRED_REQUIREMENT_FRACTION = 0.8
_UNKNOWN_REQUIREMENT_FRACTION = 0.5


def load_scoring_rules(path: Path | str | None = None) -> dict:
    if path is not None:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    local_path = Path("scoring_rules.json")
    if local_path.exists():
        return json.loads(local_path.read_text(encoding="utf-8"))
    packaged = resources.files("backstage_agent").joinpath("scoring_rules.json")
    return json.loads(packaged.read_text(encoding="utf-8"))


def score_candidate(
    features: CandidateFeatures,
    matches: list[RequirementMatch],
    rules: dict,
) -> CandidateScore:
    weights = rules["component_weights"]
    requirement_score, requirement_trace = _requirement_breakdown(
        matches,
        weights["their_requirements_match"],
    )
    subscores = {
        "their_requirements_match": requirement_score,
        "my_goal_alignment": _goal_score(features, weights["my_goal_alignment"]),
        "role_value": _role_value_score(features, weights["role_value"]),
        "project_value": _project_value_score(features, weights["project_value"]),
        "logistics": _logistics_score(features, weights["logistics"]),
        "compensation": _compensation_score(features, weights["compensation"]),
        "evidence_quality": _evidence_score(features, weights["evidence_quality"]),
    }
    raw_score = sum(subscores.values())
    caps = _score_caps(features, matches)
    capped_score = min([raw_score, *[_cap_value(cap, rules) for cap in caps]]) if caps else raw_score
    overall = max(0, min(100, int(round(capped_score))))
    return CandidateScore(
        overall_score=overall,
        score_band=_band_for_score(overall),
        subscores=subscores,
        score_caps=caps,
        positive_drivers=_positive_drivers(features, matches),
        negative_drivers=_negative_drivers(features, matches),
        score_trace=_score_trace(features, matches, requirement_trace),
        draft_suggestion=overall >= int(rules.get("draft_suggestion_min_score", 90)),
        scoring_version=str(rules["version"]),
    )


def rank_candidates(scores: list[CandidateScore], rules: dict) -> list[CandidateScore]:
    cap = int(rules.get("rank_adjustment_cap", 5))
    ranked = []
    for score in scores:
        adjustment = _rank_adjustment(score, cap)
        ranked.append(replace(score, rank_score=score.overall_score + adjustment))
    ranked.sort(key=lambda item: (item.rank_score or item.overall_score, item.overall_score), reverse=True)
    return [
        replace(score, rank_position=index)
        for index, score in enumerate(ranked, start=1)
    ]


def _requirement_score(matches: list[RequirementMatch], max_points: int) -> int:
    score, _ = _requirement_breakdown(matches, max_points)
    return score


def _requirement_breakdown(matches: list[RequirementMatch], max_points: int) -> tuple[int, dict[str, int]]:
    mandatory = [match for match in matches if match.required]
    optional = [match for match in matches if not match.required]
    if mandatory and any(match.status is RequirementStatus.NOT_MET for match in mandatory):
        return 0, {match.requirement_key: 0 for match in matches}
    if not matches:
        baseline = int(round(max_points * _NO_REQUIREMENTS_BASELINE_FRACTION))
        return baseline, {"requirements_baseline": baseline}

    if not mandatory:
        baseline = int(round(max_points * _NO_REQUIREMENTS_BASELINE_FRACTION))
        bonus_budget = int(round(max_points * _OPTIONAL_ONLY_BONUS_FRACTION))
        optional_points = _allocate_requirement_points(optional, bonus_budget)
        return baseline + sum(optional_points.values()), {
            "requirements_baseline": baseline,
            **optional_points,
        }

    mandatory_budget = int(round(max_points * _REQUIRED_REQUIREMENT_FRACTION))
    optional_budget = max_points - mandatory_budget
    mandatory_points = _allocate_requirement_points(mandatory, mandatory_budget)
    optional_points = _allocate_requirement_points(optional, optional_budget)
    return sum(mandatory_points.values()) + sum(optional_points.values()), {
        **mandatory_points,
        **optional_points,
    }


def _allocate_requirement_points(matches: list[RequirementMatch], budget: int) -> dict[str, int]:
    if budget <= 0 or not matches:
        return {}

    weights = [max(match.score_impact, 1) for match in matches]
    possible_total = sum(weights)
    if possible_total <= 0:
        return {match.requirement_key: 0 for match in matches}

    raw_points = [
        budget * weight * _status_credit(match.status) / possible_total
        for match, weight in zip(matches, weights)
    ]
    rounded_total = int(round(sum(raw_points)))
    allocated = [int(points) for points in raw_points]
    remainder = rounded_total - sum(allocated)
    ranked_indices = sorted(
        range(len(matches)),
        key=lambda index: raw_points[index] - allocated[index],
        reverse=True,
    )
    for index in ranked_indices[:remainder]:
        allocated[index] += 1
    return {
        match.requirement_key: points
        for match, points in zip(matches, allocated)
    }


def _status_credit(status: RequirementStatus) -> float:
    if status is RequirementStatus.MET:
        return 1.0
    if status in {
        RequirementStatus.UNKNOWN_NEEDS_USER_INPUT,
        RequirementStatus.NOT_APPLICABLE,
    }:
        return _UNKNOWN_REQUIREMENT_FRACTION
    return 0.0


def _goal_score(features: CandidateFeatures, max_points: int) -> int:
    alignment = str(features.project_signals.get("career_goal_alignment", "")).lower()
    if alignment == "high":
        return max_points
    if alignment == "medium":
        return int(max_points * 0.65)
    if alignment == "low":
        return int(max_points * 0.3)
    return int(max_points * 0.55)


def _role_value_score(features: CandidateFeatures, max_points: int) -> int:
    if features.role_type == "scripted_acting":
        return max_points
    if features.role_type in {"voiceover", "hosting", "commercial"}:
        return int(max_points * 0.7)
    return int(max_points * 0.45)


def _project_value_score(features: CandidateFeatures, max_points: int) -> int:
    if (
        features.project_signals.get("has_public_performance") is True
        or features.project_signals.get("public_performance") is True
    ):
        return max_points
    return int(max_points * 0.55)


def _logistics_score(features: CandidateFeatures, max_points: int) -> int:
    if features.uncertainty.get("schedule_conflict") is True:
        return int(max_points * 0.25)
    return int(max_points * 0.8)


def _compensation_score(features: CandidateFeatures, max_points: int) -> int:
    if features.compensation.get("type") == "paid":
        return max_points if features.compensation.get("amount_known") else int(max_points * 0.6)
    if features.compensation.get("type") == "unpaid":
        return int(max_points * 0.2)
    return int(max_points * 0.4)


def _evidence_score(features: CandidateFeatures, max_points: int) -> int:
    if len(features.evidence_snippets) >= 2:
        return max_points
    if features.evidence_snippets:
        return int(max_points * 0.8)
    return int(max_points * 0.3)


def _score_caps(features: CandidateFeatures, matches: list[RequirementMatch]) -> list[str]:
    caps = []
    if any(match.required and match.status is RequirementStatus.NOT_MET for match in matches):
        caps.append("mandatory_requirement_not_met")
    if features.project_signals.get("hard_personal_boundary") is True:
        caps.append("hard_personal_boundary")
    if features.project_signals.get("expired_or_unavailable") is True:
        caps.append("expired_or_unavailable")
    if features.uncertainty.get("compensation_missing") and features.uncertainty.get("role_details_sparse"):
        caps.append("missing_critical_data")
    return caps


def _cap_value(cap: str, rules: dict) -> int:
    return int(rules["score_caps"][cap])


def _band_for_score(score: int) -> ScoreBand:
    if score >= 90:
        return ScoreBand.TOP_PRIORITY
    if score >= 75:
        return ScoreBand.STRONG_CANDIDATE
    if score >= 60:
        return ScoreBand.MAYBE_REVIEW
    if score >= 40:
        return ScoreBand.LOW_PRIORITY
    return ScoreBand.NOT_WORTH_APPLYING_TODAY


def _positive_drivers(features: CandidateFeatures, matches: list[RequirementMatch]) -> list[str]:
    drivers = []
    if features.role_type == "scripted_acting":
        drivers.append("Explicit scripted acting role")
    for match in matches:
        if match.status is RequirementStatus.MET:
            drivers.append(f"{match.requirement_key} requirement met")
    return drivers


def _negative_drivers(features: CandidateFeatures, matches: list[RequirementMatch]) -> list[str]:
    drivers = []
    for match in matches:
        if match.status is RequirementStatus.NOT_MET:
            drivers.append(f"{match.requirement_key} requirement not met")
        elif match.status is RequirementStatus.UNKNOWN_NEEDS_USER_INPUT:
            drivers.append(f"{match.requirement_key} needs user input")
    if features.uncertainty.get("compensation_missing"):
        drivers.append("Compensation details missing")
    if features.uncertainty.get("role_details_sparse"):
        drivers.append("Role details sparse")
    return drivers


def _score_trace(
    features: CandidateFeatures,
    matches: list[RequirementMatch],
    requirement_trace: dict[str, int],
) -> dict:
    trace = {
        match.requirement_key: {
            "status": match.status.value,
            "points": requirement_trace.get(match.requirement_key, 0),
            "evidence": match.evidence,
            "reason": match.reason,
        }
        for match in matches
    }
    if "requirements_baseline" in requirement_trace:
        trace["requirements_baseline"] = {
            "status": "neutral_partial",
            "points": requirement_trace["requirements_baseline"],
            "evidence": "",
            "reason": "No mandatory requirements were extracted for this candidate.",
        }
    if features.project_signals.get("urgent_deadline") is not None:
        trace["urgent_deadline"] = bool(features.project_signals.get("urgent_deadline"))
    return trace


def _rank_adjustment(score: CandidateScore, cap: int) -> int:
    adjustment = 0
    if score.score_trace.get("urgent_deadline"):
        adjustment += 3
    if "missing_critical_data" in score.score_caps:
        adjustment -= 3
    return max(-cap, min(cap, adjustment))
