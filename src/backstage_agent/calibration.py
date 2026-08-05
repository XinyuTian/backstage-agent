from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime

from .candidate_models import CalibrationProposal, EvaluatedCalibrationEvidence


def historical_weight(age_days: int) -> float:
    if age_days < 0:
        raise ValueError("age_days must not be negative")
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.7
    if age_days <= 180:
        return 0.4
    return 0.2


def evaluate_calibration_evidence(
    rows: list,
    current_version: str,
    calibration_date: date,
) -> tuple[list[EvaluatedCalibrationEvidence], list[dict]]:
    evaluated = []
    excluded = []
    for row in rows:
        evidence_id = int(row["id"])
        if row["current_scoring_version"] != current_version:
            excluded.append(
                {
                    "evidence_id": evidence_id,
                    "reason": "candidate_not_scored_with_current_rules",
                }
            )
            continue
        current_score = (
            row["current_component_score"]
            if row["target_kind"] == "component"
            else row["current_overall_score"]
        )
        if current_score is None:
            excluded.append(
                {"evidence_id": evidence_id, "reason": "current_score_unavailable"}
            )
            continue
        created_at = datetime.fromisoformat(str(row["created_at"]))
        age_days = (calibration_date - created_at.date()).days
        if age_days < 0:
            excluded.append(
                {"evidence_id": evidence_id, "reason": "evidence_timestamp_in_future"}
            )
            continue
        component = str(row["component_name"])
        evaluated.append(
            EvaluatedCalibrationEvidence(
                evidence_id=evidence_id,
                stable_key=(
                    str(row["candidate_type"]),
                    str(row["project_key"]),
                    str(row["role_key"] or ""),
                    component,
                ),
                component_name=component,
                residual=int(row["human_target"]) - int(current_score),
                created_at=created_at,
                age_days=age_days,
                weight=historical_weight(age_days),
            )
        )
    return evaluated, excluded


def build_bootstrap_proposals(
    evaluated: list[EvaluatedCalibrationEvidence],
    scoring_version: str,
) -> tuple[
    list[tuple[CalibrationProposal, list[EvaluatedCalibrationEvidence]]],
    list[dict],
]:
    grouped: dict[str, dict[tuple[str, str, str, str], EvaluatedCalibrationEvidence]] = {}
    for item in evaluated:
        grouped.setdefault(item.component_name, {})[item.stable_key] = item

    proposals = []
    excluded = []
    for component, by_candidate in sorted(grouped.items()):
        supporting = list(by_candidate.values())
        recent_count = sum(item.age_days <= 30 for item in supporting)
        if recent_count >= 5:
            supporting = [
                replace(item, weight=0.0) if item.age_days > 90 else item
                for item in supporting
            ]
        effective_weight = sum(item.weight for item in supporting)
        if effective_weight <= 0:
            excluded.append(
                {"component_name": component, "reason": "zero_effective_weight"}
            )
            continue
        weighted_residual = sum(
            item.residual * item.weight for item in supporting
        ) / effective_weight
        adjustment = max(-5, min(5, round(weighted_residual)))
        fingerprint_source = "|".join(
            [scoring_version]
            + sorted(
                f"{item.evidence_id}:{item.residual}:{item.weight:.2f}"
                for item in supporting
            )
        )
        fingerprint = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
        proposal = CalibrationProposal(
            pattern_key=f"{component}:weighted_residual",
            example_count=len(supporting),
            average_delta=weighted_residual,
            affected_component=component,
            failure_mode="weighted_residual",
            proposal_text=(
                f"Bootstrap proposal: adjust {component.replace('_', ' ')} by "
                f"{adjustment:+d} points from {len(supporting)} active candidate labels."
            ),
            scoring_version=scoring_version,
            maturity_stage="bootstrap",
            proposed_adjustment=adjustment,
            effective_weight=effective_weight,
            evidence_fingerprint=fingerprint,
        )
        proposals.append((proposal, supporting))
    return proposals, excluded


def merge_calibration_patterns(pattern_groups: list[list]) -> list[dict]:
    totals: dict[tuple[str, str], dict[str, float | int | str]] = {}
    for patterns in pattern_groups:
        for row in patterns:
            component = str(row["affected_component"])
            failure_mode = str(row["failure_mode"])
            count = int(row["example_count"])
            key = (component, failure_mode)
            total = totals.setdefault(
                key,
                {
                    "affected_component": component,
                    "failure_mode": failure_mode,
                    "example_count": 0,
                    "weighted_delta": 0.0,
                },
            )
            total["example_count"] = int(total["example_count"]) + count
            total["weighted_delta"] = float(total["weighted_delta"]) + (
                float(row["average_delta"]) * count
            )

    merged = []
    for total in totals.values():
        count = int(total["example_count"])
        merged.append(
            {
                "affected_component": total["affected_component"],
                "failure_mode": total["failure_mode"],
                "example_count": count,
                "average_delta": float(total["weighted_delta"]) / count,
            }
        )
    return sorted(
        merged,
        key=lambda row: (abs(row["average_delta"]), row["example_count"]),
        reverse=True,
    )


def build_calibration_proposals(patterns: list) -> list[CalibrationProposal]:
    proposals = []
    for row in patterns:
        affected_component = str(row["affected_component"])
        failure_mode = str(row["failure_mode"])
        average_delta = float(row["average_delta"])
        proposals.append(
            CalibrationProposal(
                pattern_key=f"{affected_component}:{failure_mode}",
                example_count=int(row["example_count"]),
                average_delta=average_delta,
                affected_component=affected_component,
                failure_mode=failure_mode,
                proposal_text=_proposal_text(
                    affected_component,
                    failure_mode,
                    average_delta,
                ),
            )
        )
    return proposals


def _proposal_text(component: str, failure_mode: str, average_delta: float) -> str:
    direction = "reduce" if average_delta < 0 else "increase"
    readable_component = component.replace("_", " ")
    if component == "identity_match" and failure_mode == "overweighted_signal":
        return (
            "Proposal: reduce contextual identity-match points and award full "
            "identity-match credit only when the listing states a requirement."
        )
    if failure_mode == "overweighted_signal":
        return f"Proposal: reduce the scoring weight or cap contribution for {readable_component}."
    if failure_mode == "underweighted_signal":
        return f"Proposal: increase the scoring weight for {readable_component}."
    return (
        f"Proposal: review {readable_component} scoring because feedback suggests "
        f"a {direction} adjustment."
    )
