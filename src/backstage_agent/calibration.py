from __future__ import annotations

from .candidate_models import CalibrationProposal


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
