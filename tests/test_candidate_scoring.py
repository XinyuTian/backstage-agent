from backstage_agent.candidate_models import (
    CandidateFeatures,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)
from backstage_agent.scoring import load_scoring_rules, rank_candidates, score_candidate


def _features(**overrides):
    data = {
        "role_type": "scripted_acting",
        "project_type": "theater",
        "requirements": {},
        "project_signals": {"career_goal_alignment": "high", "public_performance": True},
        "compensation": {"type": "paid", "amount_known": True},
        "uncertainty": {"compensation_missing": False, "role_details_sparse": False},
        "evidence_snippets": ["Lead role in staged reading."],
    }
    data.update(overrides)
    return CandidateFeatures(**data)


def _rules():
    return {
        "version": "test-v1",
        "component_weights": {
            "their_requirements_match": 30,
            "my_goal_alignment": 25,
            "role_value": 15,
            "project_value": 10,
            "logistics": 10,
            "compensation": 5,
            "evidence_quality": 5,
        },
        "score_caps": {
            "mandatory_requirement_not_met": 15,
            "hard_personal_boundary": 10,
            "expired_or_unavailable": 20,
            "missing_critical_data": 60,
            "project_gate_rejected": 35,
            "project_review_blocked": 60,
        },
        "draft_suggestion_min_score": 90,
        "rank_adjustment_cap": 5,
    }


def test_score_candidate_uses_requirement_matches_and_feature_signals():
    matches = [
        RequirementMatch(
            requirement_key="instagram_profile_share",
            status=RequirementStatus.MET,
            required=True,
            local_value="true",
            evidence="Must share on Instagram.",
            reason="Stored actor profile satisfies this requirement.",
            score_impact=4,
        )
    ]

    score = score_candidate(_features(), matches, _rules())

    assert score.overall_score >= 75
    assert score.score_band in {ScoreBand.STRONG_CANDIDATE, ScoreBand.TOP_PRIORITY}
    assert score.subscores["their_requirements_match"] > 0
    assert score.subscores["their_requirements_match"] <= 30
    assert "instagram_profile_share" in score.score_trace


def test_mandatory_requirement_not_met_caps_score():
    matches = [
        RequirementMatch(
            requirement_key="instagram_profile_share",
            status=RequirementStatus.NOT_MET,
            required=True,
            local_value="",
            evidence="Must share on Instagram.",
            reason="Stored actor profile does not satisfy this requirement.",
            score_impact=0,
        )
    ]

    score = score_candidate(_features(), matches, _rules())

    assert score.overall_score == 15
    assert score.score_band is ScoreBand.NOT_WORTH_APPLYING_TODAY
    assert score.score_caps == ["mandatory_requirement_not_met"]


def test_missing_critical_data_caps_score_at_sixty():
    features = _features(uncertainty={"compensation_missing": True, "role_details_sparse": True})

    score = score_candidate(features, [], _rules())

    assert score.overall_score <= 60
    assert "missing_critical_data" in score.score_caps


def test_project_gate_rejection_caps_candidate_score():
    features = _features(project_signals={"project_gate_rejected": True})

    score = score_candidate(features, [], _rules())

    assert score.overall_score == 35
    assert "project_gate_rejected" in score.score_caps
    assert "Project gate rejected this opportunity" in score.negative_drivers


def test_project_review_blocked_caps_candidate_score():
    features = _features(project_signals={"project_review_blocked": True})

    score = score_candidate(features, [], _rules())

    assert score.overall_score <= 60
    assert "project_review_blocked" in score.score_caps


def test_optional_only_requirements_add_partial_credit_without_maxing_component():
    matches = [
        RequirementMatch(
            requirement_key="instagram_profile_share",
            status=RequirementStatus.MET,
            required=False,
            local_value="true",
            evidence="Nice to have an Instagram share.",
            reason="Stored actor profile satisfies this preference.",
            score_impact=4,
        )
    ]

    score = score_candidate(_features(), matches, _rules())

    assert 0 < score.subscores["their_requirements_match"] < 30


def test_no_extracted_requirements_receive_neutral_partial_credit():
    score = score_candidate(_features(), [], _rules())

    assert score.subscores["their_requirements_match"] == 15


def test_requirement_trace_points_match_awarded_requirement_points():
    matches = [
        RequirementMatch(
            requirement_key="instagram_profile_share",
            status=RequirementStatus.MET,
            required=True,
            local_value="true",
            evidence="Must share on Instagram.",
            reason="Stored actor profile satisfies this requirement.",
            score_impact=4,
        ),
        RequirementMatch(
            requirement_key="self_tape",
            status=RequirementStatus.UNKNOWN_NEEDS_USER_INPUT,
            required=False,
            local_value="unknown",
            evidence="Self-tape preferred.",
            reason="No stored preference for this ask.",
            score_impact=2,
        ),
    ]

    score = score_candidate(_features(), matches, _rules())
    requirement_points = sum(
        trace_entry["points"]
        for key, trace_entry in score.score_trace.items()
        if key in {"instagram_profile_share", "self_tape"}
    )

    assert requirement_points == score.subscores["their_requirements_match"]


def test_rank_candidates_applies_small_adjustments_without_overpowering_score():
    low = score_candidate(_features(project_signals={"urgent_deadline": True}), [], _rules())
    high = score_candidate(_features(project_signals={"urgent_deadline": False}), [], _rules())
    low = low.__class__(**{**low.__dict__, "overall_score": 55})
    high = high.__class__(**{**high.__dict__, "overall_score": 85})

    ranked = rank_candidates([low, high], _rules())

    assert ranked[0].overall_score == 85
    assert ranked[0].rank_position == 1
    assert ranked[1].rank_position == 2


def test_load_scoring_rules_does_not_require_repo_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    rules = load_scoring_rules()

    assert rules["version"]
    assert "component_weights" in rules
