from backstage_agent.candidate_models import (
    CandidateFeatures,
    CalibrationProposal,
    CandidateInput,
    CandidateScore,
    CandidateType,
    HumanFeedback,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)


def test_candidate_input_accepts_role_or_project_only(casting_notice_factory):
    role = casting_notice_factory(role="Lead")

    candidate = CandidateInput.role_candidate(
        project_id=7,
        role_id=9,
        project_key="project-key",
        role_key="role-key",
        title="Play - Lead",
        notice=role,
    )

    assert candidate.candidate_type is CandidateType.ROLE
    assert candidate.source_project_id == 7
    assert candidate.source_role_id == 9
    assert candidate.role_key == "role-key"
    assert candidate.notice is role


def test_project_only_candidate_has_no_role_id():
    candidate = CandidateInput.project_only_candidate(
        project_id=3,
        project_key="project-key",
        title="General Project Opportunity",
        source_message_id="m1",
        description="Project has no explicit parsed roles.",
        application_url="https://example.test/apply",
    )

    assert candidate.candidate_type is CandidateType.PROJECT_ONLY
    assert candidate.source_role_id is None
    assert candidate.role_key == ""
    assert candidate.notice.role is None


def test_candidate_score_clamps_to_band():
    score = CandidateScore(
        overall_score=86,
        score_band=ScoreBand.STRONG_CANDIDATE,
        subscores={"their_requirements_match": 27},
        score_caps=[],
        positive_drivers=["Explicit role fit"],
        negative_drivers=[],
        score_trace={"role_fit": {"points": 12}},
        draft_suggestion=True,
        scoring_version="2026-07-13-v1",
    )

    assert score.overall_score == 86
    assert score.score_band is ScoreBand.STRONG_CANDIDATE
    assert score.draft_suggestion is True


def test_requirement_match_status_values_are_stable():
    assert RequirementStatus.MET.value == "met"
    assert RequirementStatus.NOT_MET.value == "not_met"
    assert RequirementStatus.UNKNOWN_NEEDS_USER_INPUT.value == "unknown_needs_user_input"
    assert RequirementStatus.NOT_APPLICABLE.value == "not_applicable"


def test_candidate_features_keeps_raw_payload_for_audit():
    features = CandidateFeatures(
        role_type="scripted_acting",
        project_type="theater",
        requirements={"instagram_profile_share": {"required": True}},
        project_signals={"has_public_performance": True},
        compensation={"type": "paid"},
        uncertainty={"compensation_missing": False},
        evidence_snippets=["Requires sharing on Instagram profile."],
        raw={"model": "payload"},
    )

    assert features.requirements["instagram_profile_share"]["required"] is True
    assert features.raw == {"model": "payload"}


def test_requirement_match_records_local_fact_source():
    match = RequirementMatch(
        requirement_key="instagram_profile_share",
        status=RequirementStatus.MET,
        required=True,
        local_value="yes",
        evidence="Listing requires an Instagram profile share.",
        reason="Actor profile allows active Instagram tagging/sharing.",
        score_impact=4,
    )

    assert match.status is RequirementStatus.MET
    assert match.score_impact == 4


def test_human_feedback_score_delta_uses_human_minus_agent():
    feedback = HumanFeedback(
        candidate_id=42,
        agent_score=61,
        human_score=73,
        affected_components=["their_requirements_match"],
        failure_modes=["missed local preference"],
        free_text_reason="The agent underweighted the requirement fit.",
    )

    assert feedback.score_delta == 12
    assert feedback.calibration_status == "unreviewed_for_calibration"


def test_calibration_proposal_defaults_status_to_proposed():
    proposal = CalibrationProposal(
        pattern_key="instagram_profile_share",
        example_count=3,
        average_delta=4.5,
        affected_component="their_requirements_match",
        failure_mode="missed local preference",
        proposal_text="Increase weight for active Instagram tagging.",
    )

    assert proposal.status == "proposed"
