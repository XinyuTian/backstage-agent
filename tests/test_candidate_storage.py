import json
import sqlite3
from dataclasses import replace
from datetime import date

from backstage_agent.candidate_models import (
    CalibrationEvidence,
    CalibrationProposal,
    CandidateFeatures,
    CandidateComponentCorrection,
    CandidateInput,
    CandidateScore,
    HumanFeedback,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
    ScoringSnapshot,
)
from backstage_agent.models import ProjectNotice
from backstage_agent.storage import DecisionStore


def _calibration_evidence(candidate_id: int, human_target: int = 8) -> CalibrationEvidence:
    return CalibrationEvidence(
        source_type="dashboard_correction",
        source_id=str(candidate_id),
        candidate_type="role",
        project_key="project",
        role_key="role",
        candidate_id_at_submission=candidate_id,
        component_name="role_value",
        failure_mode="subscore_override",
        target_kind="component",
        human_target=human_target,
        submitted_agent_score=15,
        scoring_version="test-v1",
    )


def test_latest_calibration_evidence_supersedes_same_role_component(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    first_id = store.record_calibration_evidence(_calibration_evidence(10, 8))
    second_id = store.record_calibration_evidence(_calibration_evidence(11, 12))

    active = store.active_calibration_evidence()
    history = store.calibration_evidence_history("role", "project", "role", "role_value")

    assert [row["id"] for row in active] == [second_id]
    assert [row["id"] for row in history] == [second_id, first_id]
    assert history[1]["superseded_at"] is not None


def test_calibration_evidence_keeps_different_metrics_active(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    store.record_calibration_evidence(_calibration_evidence(10, 8))
    store.record_calibration_evidence(
        replace(_calibration_evidence(10, 4), component_name="logistics")
    )

    assert {row["component_name"] for row in store.active_calibration_evidence()} == {
        "role_value",
        "logistics",
    }


def test_calibration_identity_survives_candidate_rescore_id_change(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    first_id = store.record_calibration_evidence(_calibration_evidence(10, 8))
    second_id = store.record_calibration_evidence(_calibration_evidence(99, 9))

    assert second_id != first_id
    assert store.active_calibration_evidence()[0]["candidate_id_at_submission"] == 99
    assert len(
        store.calibration_evidence_history("role", "project", "role", "role_value")
    ) == 2


def test_legacy_rows_are_preserved_without_runtime_access(tmp_path):
    database_path = tmp_path / "db.sqlite3"
    store = DecisionStore(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO decisions (
              source_message_id, title, score, should_apply, reasons_json,
              concerns_json, llm_used, notice_json
            )
            VALUES ('legacy-message', 'Legacy Decision', 0.5, 0, '[]', '[]', 0, '{}')
            """
        )
        connection.execute(
            """
            INSERT INTO applications (title, cover_note, dry_run, status)
            VALUES ('Legacy Decision', 'Old draft', 1, 'drafted')
            """
        )

    store = DecisionStore(database_path)

    for name in (
        "record_decision",
        "record_review",
        "record_application",
        "recent_decisions",
        "get_decision",
        "search_decisions",
        "decision_counts",
        "screening_counts",
    ):
        assert not hasattr(store, name)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1


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


def test_component_correction_upsert_replaces_only_matching_component(
    tmp_path,
    casting_notice_factory,
):
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

    def correction(component, corrected, reason=""):
        return CandidateComponentCorrection(
            candidate_type="role",
            project_key="project",
            role_key="role",
            candidate_id_at_submission=candidate_id,
            component_name=component,
            agent_component_score=15 if component == "role_value" else 8,
            corrected_component_score=corrected,
            reason=reason,
            scoring_version="test-v1",
            component_max_at_correction=15 if component == "role_value" else 10,
        )

    first_id = store.upsert_candidate_correction(
        correction("role_value", 10, "Too generous")
    )
    second_id = store.upsert_candidate_correction(
        correction("role_value", 8, "Final value")
    )
    store.upsert_candidate_correction(correction("logistics", 6))

    key = ("role", "project", "role")
    rows = store.corrections_for_candidate_keys([key])[key]

    assert second_id == first_id
    assert {
        (row["component_name"], row["corrected_component_score"])
        for row in rows
    } == {("role_value", 8), ("logistics", 6)}
    assert next(
        row for row in rows if row["component_name"] == "role_value"
    )["reason"] == "Final value"
    role_history = store.calibration_evidence_history(
        "role", "project", "role", "role_value"
    )
    assert [row["human_target"] for row in role_history] == [8, 10]
    assert role_history[1]["superseded_at"] is not None
    assert store.calibration_evidence_history(
        "role", "project", "role", "logistics"
    )[0]["human_target"] == 6


def test_component_correction_reset_removes_only_matching_component(
    tmp_path,
    casting_notice_factory,
):
    store = DecisionStore(tmp_path / "db.sqlite3")
    candidate_id = store.record_candidate(
        CandidateInput.project_only_candidate(
            project_id=1,
            project_key="project",
            title="Project",
            source_message_id="m1",
            description="Description",
            application_url=None,
        ),
        _features(),
        [],
        _score(),
    )
    for component in ("role_value", "logistics"):
        store.upsert_candidate_correction(
            CandidateComponentCorrection(
                candidate_type="project_only",
                project_key="project",
                role_key="",
                candidate_id_at_submission=candidate_id,
                component_name=component,
                agent_component_score=10,
                corrected_component_score=7,
                reason="",
                scoring_version="test-v1",
                component_max_at_correction=15,
            )
        )

    assert store.delete_candidate_correction(
        "project_only", "project", "", "role_value"
    )
    rows = store.corrections_for_candidate_keys(
        [("project_only", "project", "")]
    )[("project_only", "project", "")]

    assert [row["component_name"] for row in rows] == ["logistics"]
    assert {
        row["component_name"] for row in store.active_calibration_evidence()
    } == {"logistics"}
    role_value_history = store.calibration_evidence_history(
        "project_only", "project", "", "role_value"
    )
    assert role_value_history[0]["superseded_at"] is not None


def test_workbench_rows_use_effective_project_date_order(
    tmp_path,
    casting_notice_factory,
):
    store = DecisionStore(tmp_path / "db.sqlite3")
    for title, key, project_date, seen_date, score_value in (
        ("Old", "old-project", date(2026, 7, 20), date(2026, 7, 24), 95),
        ("New", "new-project", date(2026, 7, 24), date(2026, 7, 24), 45),
    ):
        project_id = store.upsert_project(
            ProjectNotice(
                source_message_id=key,
                title=title,
                project_url=f"https://example.com/{key}",
                description=title,
                raw_text=title,
                project_date=project_date,
                project_key=key,
            ),
            seen_date=seen_date,
        )
        candidate = CandidateInput.project_only_candidate(
            project_id=project_id,
            project_key=key,
            title=title,
            source_message_id=key,
            description=title,
            application_url=None,
        )
        store.record_candidate(
            candidate,
            _features(),
            [],
            replace(_score(), overall_score=score_value),
        )

    rows = store.search_candidate_workbench_rows()

    assert [row["project_key"] for row in rows] == ["new-project", "old-project"]
    assert rows[0]["effective_project_date"] == "2026-07-24"
    assert rows[1]["effective_project_date"] == "2026-07-20"


def test_workbench_rows_filter_by_exact_day_and_seven_day_window(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    for title, key, project_date in (
        ("Outside", "outside-project", date(2026, 7, 17)),
        ("Window Start", "window-start-project", date(2026, 7, 18)),
        ("Exact Day", "exact-day-project", date(2026, 7, 23)),
    ):
        project_id = store.upsert_project(
            ProjectNotice(
                source_message_id=key,
                title=title,
                project_url=f"https://example.com/{key}",
                description=title,
                raw_text=title,
                project_date=project_date,
                project_key=key,
            ),
            seen_date=date(2026, 7, 24),
        )
        store.record_candidate(
            CandidateInput.project_only_candidate(
                project_id=project_id,
                project_key=key,
                title=title,
                source_message_id=key,
                description=title,
                application_url=None,
            ),
            _features(),
            [],
            _score(),
        )

    rows = store.search_candidate_workbench_rows(date_end="2026-07-23", days=1)
    assert [row["effective_project_date"] for row in rows] == ["2026-07-23"]
    assert [row["project_key"] for row in rows] == ["exact-day-project"]

    rows = store.search_candidate_workbench_rows(date_end="2026-07-24", days=7)
    assert {row["effective_project_date"] for row in rows} == {
        "2026-07-18",
        "2026-07-23",
    }


def test_correction_patterns_count_only_latest_component_value(
    tmp_path,
    casting_notice_factory,
):
    store = DecisionStore(tmp_path / "db.sqlite3")
    snapshot = ScoringSnapshot(
        version="test-v1",
        component_maxima={"role_value": 15},
        cap_values={},
        band_thresholds={
            "top_priority": 90,
            "strong_candidate": 75,
            "maybe_review": 60,
            "low_priority": 40,
        },
    )
    for index, corrected in ((1, 8), (2, 13)):
        project_key = f"project-{index}"
        role_key = f"role-{index}"
        candidate_id = store.record_candidate(
            CandidateInput.role_candidate(
                project_id=index,
                role_id=index,
                project_key=project_key,
                role_key=role_key,
                title=f"Role {index}",
                notice=casting_notice_factory(),
            ),
            _features(),
            [],
            replace(_score(), scoring_snapshot=snapshot),
        )
        store.upsert_candidate_correction(
            CandidateComponentCorrection(
                candidate_type="role",
                project_key=project_key,
                role_key=role_key,
                candidate_id_at_submission=candidate_id,
                component_name="role_value",
                agent_component_score=15,
                corrected_component_score=corrected,
                reason="",
                scoring_version="test-v1",
                component_max_at_correction=15,
            )
        )
        if index == 1:
            store.upsert_candidate_correction(
                CandidateComponentCorrection(
                    candidate_type="role",
                    project_key=project_key,
                    role_key=role_key,
                    candidate_id_at_submission=candidate_id,
                    component_name="role_value",
                    agent_component_score=15,
                    corrected_component_score=10,
                    reason="Final",
                    scoring_version="test-v1",
                    component_max_at_correction=15,
                )
            )

    patterns = store.correction_patterns(min_examples=2)

    assert patterns[0]["affected_component"] == "role_value"
    assert patterns[0]["example_count"] == 2
    assert patterns[0]["average_delta"] == -3.5


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


def test_record_candidate_feedback_expands_components_into_active_evidence(
    tmp_path,
    casting_notice_factory,
):
    store = DecisionStore(tmp_path / "db.sqlite3")
    candidate_id = store.record_candidate(
        CandidateInput.role_candidate(
            project_id=1,
            role_id=2,
            project_key="project",
            role_key="role",
            title="Play - Lead",
            notice=casting_notice_factory(),
        ),
        _features(),
        [_match()],
        _score(),
    )

    feedback_id = store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=80,
            human_score=60,
            affected_components=["role_value", "logistics"],
            failure_modes=["overweighted_signal"],
            free_text_reason="Both are too high.",
        )
    )

    evidence = store.active_calibration_evidence()
    assert {(row["component_name"], row["source_id"]) for row in evidence} == {
        ("role_value", str(feedback_id)),
        ("logistics", str(feedback_id)),
    }
    assert all(row["target_kind"] == "overall" for row in evidence)


def test_existing_feedback_is_backfilled_with_latest_active(
    tmp_path,
    casting_notice_factory,
):
    database_path = tmp_path / "db.sqlite3"
    store = DecisionStore(database_path)
    candidate_id = store.record_candidate(
        CandidateInput.role_candidate(
            project_id=1,
            role_id=2,
            project_key="project",
            role_key="role",
            title="Play - Lead",
            notice=casting_notice_factory(),
        ),
        _features(),
        [_match()],
        _score(),
    )
    with store._connect() as conn:
        conn.execute("DELETE FROM candidate_calibration_evidence")
        for human_score in (50, 70):
            conn.execute(
                """
                INSERT INTO candidate_feedback (
                  candidate_id, agent_score, human_score, score_delta,
                  affected_components_json, failure_modes_json,
                  free_text_reason, calibration_status
                ) VALUES (?, 80, ?, ?, '["role_value"]',
                          '["overweighted_signal"]', 'Legacy',
                          'unreviewed_for_calibration')
                """,
                (candidate_id, human_score, human_score - 80),
            )

    migrated = DecisionStore(database_path)
    history = migrated.calibration_evidence_history(
        "role", "project", "role", "role_value"
    )

    assert [row["human_target"] for row in history] == [70, 50]
    assert history[0]["superseded_at"] is None
    assert history[1]["superseded_at"] is not None


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
