from datetime import date, datetime

import pytest

from backstage_agent.calibration import (
    build_bootstrap_proposals,
    build_calibration_proposals,
    evaluate_calibration_evidence,
    historical_weight,
    merge_calibration_patterns,
)
from backstage_agent.candidate_models import EvaluatedCalibrationEvidence


def _evaluated(
    evidence_id: int,
    residual: int,
    age_days: int,
    component: str = "role_value",
) -> EvaluatedCalibrationEvidence:
    return EvaluatedCalibrationEvidence(
        evidence_id=evidence_id,
        stable_key=("role", f"project-{evidence_id}", f"role-{evidence_id}", component),
        component_name=component,
        residual=residual,
        created_at=datetime(2026, 8, 4) if age_days == 0 else datetime(2026, 8, 4),
        age_days=age_days,
        weight=historical_weight(age_days),
    )


def test_evaluate_component_evidence_uses_current_score():
    rows = [
        {
            "id": 1,
            "candidate_type": "role",
            "project_key": "p",
            "role_key": "r",
            "component_name": "role_value",
            "target_kind": "component",
            "human_target": 8,
            "current_component_score": 15,
            "current_overall_score": 80,
            "current_scoring_version": "v2",
            "created_at": "2026-08-01 00:00:00",
        }
    ]

    evaluated, excluded = evaluate_calibration_evidence(
        rows, "v2", date(2026, 8, 4)
    )

    assert evaluated[0].residual == -7
    assert evaluated[0].age_days == 3
    assert evaluated[0].weight == 1.0
    assert excluded == []


def test_incompatible_current_version_is_excluded():
    rows = [
        {
            "id": 1,
            "candidate_type": "role",
            "project_key": "p",
            "role_key": "r",
            "component_name": "role_value",
            "target_kind": "component",
            "human_target": 8,
            "current_component_score": 15,
            "current_overall_score": 80,
            "current_scoring_version": "v1",
            "created_at": "2026-08-01 00:00:00",
        }
    ]

    evaluated, excluded = evaluate_calibration_evidence(
        rows, "v2", date(2026, 8, 4)
    )

    assert evaluated == []
    assert excluded[0]["reason"] == "candidate_not_scored_with_current_rules"


@pytest.mark.parametrize(
    ("age_days", "expected"),
    [(0, 1.0), (30, 1.0), (31, 0.7), (90, 0.7), (91, 0.4), (180, 0.4), (181, 0.2)],
)
def test_historical_weight_boundaries(age_days, expected):
    assert historical_weight(age_days) == expected


def test_bootstrap_proposal_is_bounded_at_five_points():
    evaluated = [_evaluated(index, -12, 0) for index in range(1, 4)]

    proposals, excluded = build_bootstrap_proposals(evaluated, "v2")
    proposal, supporting = proposals[0]

    assert proposal.maturity_stage == "bootstrap"
    assert proposal.example_count == 3
    assert proposal.proposed_adjustment == -5
    assert proposal.effective_weight == 3.0
    assert len(supporting) == 3
    assert excluded == []


def test_five_recent_labels_make_old_evidence_stability_only():
    evaluated = [_evaluated(index, 5, 10) for index in range(1, 6)]
    evaluated.append(_evaluated(6, -20, 120))

    proposals, excluded = build_bootstrap_proposals(evaluated, "v2")
    proposal, supporting = proposals[0]

    assert proposal.example_count == 6
    assert proposal.proposed_adjustment == 5
    assert proposal.effective_weight == 5.0
    assert [item.weight for item in supporting if item.age_days > 90] == [0.0]
    assert excluded == []


def test_weighted_residual_reduces_old_feedback_influence():
    evaluated = [_evaluated(1, 5, 10), _evaluated(2, -10, 200)]

    proposal = build_bootstrap_proposals(evaluated, "v2")[0][0][0]

    assert proposal.average_delta == pytest.approx(2.5)
    assert proposal.proposed_adjustment == 2


def test_build_calibration_proposal_for_overweighted_identity_signal():
    patterns = [
        {
            "affected_component": "identity_match",
            "failure_mode": "overweighted_signal",
            "example_count": 4,
            "average_delta": -28.0,
        }
    ]

    proposals = build_calibration_proposals(patterns)

    assert proposals[0].pattern_key == "identity_match:overweighted_signal"
    assert proposals[0].example_count == 4
    assert proposals[0].average_delta == -28.0
    assert "reduce" in proposals[0].proposal_text.lower()
    assert "identity" in proposals[0].proposal_text.lower()


def test_build_calibration_proposal_for_underweighted_signal():
    patterns = [
        {
            "affected_component": "compensation",
            "failure_mode": "underweighted_signal",
            "example_count": 3,
            "average_delta": 18.5,
        }
    ]

    proposals = build_calibration_proposals(patterns)

    assert proposals[0].pattern_key == "compensation:underweighted_signal"
    assert "increase" in proposals[0].proposal_text.lower()


def test_merge_calibration_patterns_uses_weighted_average():
    merged = merge_calibration_patterns(
        [
            [
                {
                    "affected_component": "role_value",
                    "failure_mode": "subscore_override",
                    "example_count": 2,
                    "average_delta": -4.0,
                }
            ],
            [
                {
                    "affected_component": "role_value",
                    "failure_mode": "subscore_override",
                    "example_count": 1,
                    "average_delta": 2.0,
                }
            ],
        ]
    )

    assert merged == [
        {
            "affected_component": "role_value",
            "failure_mode": "subscore_override",
            "example_count": 3,
            "average_delta": -2.0,
        }
    ]
