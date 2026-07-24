import json
from dataclasses import replace
from datetime import date

from backstage_agent.candidate_models import (
    CalibrationProposal,
    CandidateFeatures,
    CandidateInput,
    CandidateScore,
    HumanFeedback,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)
from backstage_agent.models import ProjectNotice
from backstage_agent.storage import DecisionStore


def _features():
    return CandidateFeatures(
        role_type="scripted_acting",
        project_type="theater",
        requirements={},
        project_signals={},
        compensation={},
        uncertainty={},
        evidence_snippets=["Evidence"],
    )


def _match():
    return RequirementMatch(
        requirement_key="instagram_profile_share",
        status=RequirementStatus.MET,
        required=True,
        local_value="true",
        evidence="Must share.",
        reason="Stored fact matches.",
        score_impact=4,
    )


def _score():
    return CandidateScore(
        overall_score=86,
        score_band=ScoreBand.STRONG_CANDIDATE,
        subscores={"their_requirements_match": 30},
        score_caps=[],
        positive_drivers=["Good fit"],
        negative_drivers=[],
        score_trace={"instagram_profile_share": {"points": 4}},
        draft_suggestion=False,
        scoring_version="test-v1",
        rank_score=87,
        rank_position=1,
    )


def test_record_and_search_candidate(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )

    candidate_id = store.record_candidate(candidate, _features(), [_match()], _score())
    rows = store.search_candidates()

    assert candidate_id == rows[0]["id"]
    assert rows[0]["overall_score"] == 86
    assert rows[0]["score_band"] == "strong_candidate"
    assert json.loads(rows[0]["features_json"])["role_type"] == "scripted_acting"
    assert (
        json.loads(rows[0]["requirement_match_json"])[0]["requirement_key"]
        == "instagram_profile_share"
    )


def test_feedback_patterns_group_taxonomy(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )
    candidate_id = store.record_candidate(candidate, _features(), [_match()], _score())

    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=86,
            human_score=45,
            affected_components=["identity_match"],
            failure_modes=["overweighted_signal"],
            free_text_reason="Nationality over-weighted.",
        )
    )
    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=80,
            human_score=50,
            affected_components=["identity_match"],
            failure_modes=["overweighted_signal"],
            free_text_reason="Same issue.",
        )
    )

    patterns = store.feedback_patterns(min_examples=2)

    assert patterns[0]["affected_component"] == "identity_match"
    assert patterns[0]["failure_mode"] == "overweighted_signal"
    assert patterns[0]["example_count"] == 2
    assert patterns[0]["average_delta"] < 0


def test_feedback_patterns_expand_all_taxonomy_pairs(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )
    candidate_id = store.record_candidate(candidate, _features(), [_match()], _score())

    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=90,
            human_score=60,
            affected_components=["identity_match", "project_signal_match"],
            failure_modes=["overweighted_signal", "missing_context"],
            free_text_reason="Multiple scoring issues.",
        )
    )
    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=88,
            human_score=58,
            affected_components=["project_signal_match"],
            failure_modes=["missing_context"],
            free_text_reason="Project context was underweighted again.",
        )
    )

    patterns = {
        (row["affected_component"], row["failure_mode"]): row
        for row in store.feedback_patterns(min_examples=2)
    }

    assert ("project_signal_match", "missing_context") in patterns
    assert patterns[("project_signal_match", "missing_context")]["example_count"] == 2
    assert patterns[("project_signal_match", "missing_context")]["average_delta"] < 0


def test_record_calibration_proposal_persists_fields(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")

    proposal_id = store.record_calibration_proposal(
        CalibrationProposal(
            pattern_key="project_signal_match:missing_context",
            example_count=3,
            average_delta=-24.5,
            affected_component="project_signal_match",
            failure_mode="missing_context",
            proposal_text="Reduce project signal weight when context is sparse.",
            status="accepted",
        )
    )

    with store._connect() as conn:
        row = conn.execute(
            """
            SELECT pattern_key, example_count, average_delta, affected_component,
                   failure_mode, proposal_text, status
            FROM calibration_proposals
            WHERE id = ?
            """,
            (proposal_id,),
        ).fetchone()

    assert row is not None
    assert row[0] == "project_signal_match:missing_context"
    assert row[1] == 3
    assert row[2] == -24.5
    assert row[3] == "project_signal_match"
    assert row[4] == "missing_context"
    assert row[5] == "Reduce project signal weight when context is sparse."
    assert row[6] == "accepted"


def test_candidate_rescore_sources_and_clear_by_date(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    project_id = store.record_project(
        ProjectNotice(
            source_message_id="m1",
            title="Stored Project",
            project_url="https://example.com/project",
            description="Project description",
            raw_text="Project raw text",
            project_date=date(2026, 7, 13),
            project_key="stored-project",
        )
    )
    role = casting_notice_factory(
        title="Stored Project - Lead",
        project="Stored Project",
        role="Lead",
        project_key="stored-project",
        role_key="stored-role",
        project_date=date(2026, 7, 13),
    )
    role_id = store.record_role(project_id, role)
    store.record_candidate(
        CandidateInput.role_candidate(
            project_id=project_id,
            role_id=role_id,
            project_key="stored-project",
            role_key="stored-role",
            title=role.title,
            notice=role,
        ),
        _features(),
        [_match()],
        _score(),
    )

    sources = store.candidate_rescore_sources_for_date("2026-07-13")

    assert len(sources) == 1
    assert sources[0][0].title == "Stored Project"
    assert sources[0][1][0][0] == role_id
    assert sources[0][1][0][1].role == "Lead"
    assert store.clear_candidates_for_date("2026-07-13") == 1
    assert store.search_candidates() == []


def test_upsert_project_and_role_refresh_newest_data_without_new_ids(
    tmp_path,
    casting_notice_factory,
):
    store = DecisionStore(tmp_path / "db.sqlite3")
    old_project = ProjectNotice(
        source_message_id="old-message",
        title="Repeated Project",
        project_url="https://example.com/project",
        description="Old description",
        raw_text="Old raw text",
        project_date=date(2026, 7, 10),
        project_key="repeated-project",
    )
    project_id = store.upsert_project(old_project, seen_date=date(2026, 7, 10))
    old_role = casting_notice_factory(
        source_message_id="old-message",
        project_key="repeated-project",
        role_key="repeated-role",
        compensation="$50",
        description="Old role data",
        project_date=date(2026, 7, 10),
    )
    role_id = store.upsert_role(project_id, old_role)

    refreshed_project = replace(
        old_project,
        source_message_id="new-message",
        description="Newest description",
        raw_text="Newest raw text",
    )
    refreshed_role = replace(
        old_role,
        source_message_id="new-message",
        compensation="$500",
        description="Newest role data",
    )

    assert store.upsert_project(refreshed_project, seen_date=date(2026, 7, 15)) == project_id
    assert store.upsert_role(project_id, refreshed_role) == role_id
    sources = store.candidate_rescore_sources_for_date("2026-07-15")
    assert len(sources) == 1
    assert sources[0][0].description == "Newest description"
    assert sources[0][1][0][0] == role_id
    assert sources[0][1][0][1].compensation == "$500"


def test_candidate_rows_for_date_and_clear_preserve_feedback(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    project_id = store.upsert_project(
        ProjectNotice(
            source_message_id="m1",
            title="Stored Project",
            project_url="https://example.com/project",
            description="Description",
            raw_text="Raw",
            project_date=date(2026, 7, 15),
            project_key="stored-project",
        ),
        seen_date=date(2026, 7, 15),
    )
    role = casting_notice_factory(
        project_key="stored-project",
        role_key="stored-role",
        project_date=date(2026, 7, 15),
    )
    role_id = store.upsert_role(project_id, role)
    candidate_id = store.record_candidate(
        CandidateInput.role_candidate(
            project_id=project_id,
            role_id=role_id,
            project_key="stored-project",
            role_key="stored-role",
            title=role.title,
            notice=role,
        ),
        _features(),
        [_match()],
        _score(),
    )
    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=86,
            human_score=60,
            affected_components=["identity_match"],
            failure_modes=["overweighted_signal"],
            free_text_reason="Keep me",
        )
    )

    rows = store.candidate_rows_for_date("2026-07-15")
    assert [(row["candidate_type"], row["role_key"]) for row in rows] == [
        ("role", "stored-role")
    ]
    assert store.clear_candidates_for_date("2026-07-15") == 1
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_feedback").fetchone()[0] == 1
        assert conn.execute("SELECT candidate_id FROM candidate_feedback").fetchone()[0] == candidate_id
