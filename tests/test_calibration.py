from backstage_agent.calibration import (
    build_calibration_proposals,
    merge_calibration_patterns,
)


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
