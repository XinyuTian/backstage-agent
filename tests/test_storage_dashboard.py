from backstage_agent.models import (
    ApplicationDraft,
    CastingNotice,
    ProjectNotice,
    ReviewDecision,
    ScreeningDecision,
)
from backstage_agent.project_screener import project_to_notice
from backstage_agent.storage import DecisionStore
from backstage_agent.ui import _decision_status, _reviewer_detail


def _notice(title: str) -> CastingNotice:
    return CastingNotice(
        source_message_id="m1",
        title=title,
        project="Project",
        role=title,
        location=None,
        compensation=None,
        description=title,
        application_url=None,
        raw_text=title,
        role_key=title.lower().replace(" ", "-"),
    )


def test_reviewer_rejected_counts_as_needs_check_not_rejected(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    screened_out = ScreeningDecision(
        notice=_notice("Screened Out"),
        score=0.0,
        should_apply=False,
        reasons=["Rejected locally."],
    )
    needs_check = ScreeningDecision(
        notice=_notice("Reviewer Rejected"),
        score=0.85,
        should_apply=True,
        reasons=["Passed first-pass screening."],
        llm_used=True,
    )

    store.record_decision(screened_out)
    decision_id = store.record_decision(needs_check)
    store.record_review(
        decision_id,
        ReviewDecision(
            notice=needs_check.notice,
            status="rejected",
            score=0.2,
            reasons=["Reviewer found a conflict."],
        ),
    )

    counts = store.decision_counts()
    rejected = store.search_decisions(decision="reject")
    needs_check_rows = store.search_decisions(decision="needs_check")

    assert counts["reject_count"] == 1
    assert counts["needs_check_count"] == 1
    assert [row["title"] for row in rejected] == ["Screened Out"]
    assert [row["title"] for row in needs_check_rows] == ["Reviewer Rejected"]


def test_approved_project_gate_is_hidden_but_unresolved_project_gates_show(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    approved_gate = ScreeningDecision(
        notice=project_to_notice(_project("Approved Project")),
        score=0.9,
        should_apply=True,
        reasons=["Passed project screening."],
        llm_used=True,
    )
    rejected_gate = ScreeningDecision(
        notice=project_to_notice(_project("Rejected Project")),
        score=0.0,
        should_apply=False,
        reasons=["Rejected by project screening."],
        llm_used=True,
    )
    needs_check_gate = ScreeningDecision(
        notice=project_to_notice(_project("Needs Check Project")),
        score=0.8,
        should_apply=True,
        reasons=["Passed project screening."],
        llm_used=True,
    )

    approved_id = store.record_decision(approved_gate)
    store.record_review(
        approved_id,
        ReviewDecision(
            notice=approved_gate.notice,
            status="approved",
            score=0.9,
            reasons=["Project approved."],
        ),
    )
    store.record_decision(rejected_gate)
    needs_check_id = store.record_decision(needs_check_gate)
    store.record_review(
        needs_check_id,
        ReviewDecision(
            notice=needs_check_gate.notice,
            status="rejected",
            score=0.2,
            reasons=["Project reviewer found a conflict."],
        ),
    )

    rows = store.search_decisions()
    counts = store.decision_counts()

    assert [row["title"] for row in rows] == [
        "Needs Check Project - Project Gate",
        "Rejected Project - Project Gate",
    ]
    assert counts["total"] == 2
    assert counts["passed_count"] == 0
    assert counts["needs_check_count"] == 1
    assert counts["reject_count"] == 1


def test_store_persists_structured_decision_artifacts(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    decision = ScreeningDecision(
        notice=_notice("Structured Role"),
        score=0.91,
        should_apply=True,
        reasons=["Named scripted role"],
        llm_used=True,
        final_bucket="auto_apply_draft",
        classifier_json={"role_type": "scripted_acting"},
        reviewer_impact="not_reviewed",
    )

    decision_id = store.record_decision(decision)
    store.record_review(
        decision_id,
        ReviewDecision(
            notice=decision.notice,
            status="hold",
            score=0.8,
            reasons=["Needs eyeballing"],
            final_bucket="ready_for_review",
            reviewer_json={"verdict": "downgrade"},
            reviewer_impact="downgraded",
        ),
    )

    row = store.search_decisions()[0]

    assert row["final_bucket"] == "ready_for_review"
    assert row["classifier_json"] == '{"role_type": "scripted_acting"}'
    assert row["reviewer_json"] == '{"verdict": "downgrade"}'
    assert row["reviewer_impact"] == "downgraded"
    assert _decision_status(row)[0] == "Ready For Review"
    assert "Reviewer impact: downgraded" in _reviewer_detail(row)


def test_store_returns_latest_cover_note_for_dashboard(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    decision = ScreeningDecision(
        notice=_notice("Cover Letter Role"),
        score=0.91,
        should_apply=True,
        reasons=["Passed screening."],
        final_bucket="auto_apply_draft",
    )

    decision_id = store.record_decision(decision)
    store.record_application(
        ApplicationDraft(
            notice=decision.notice,
            cover_note="Older cover letter",
            dry_run=True,
            status="drafted",
        )
    )
    store.record_application(
        ApplicationDraft(
            notice=decision.notice,
            cover_note="Latest cover letter",
            dry_run=True,
            status="drafted",
        )
    )

    row = store.get_decision(decision_id)
    rows = store.search_decisions()

    assert row is not None
    assert row["title"] == "Cover Letter Role"
    assert rows[0]["cover_note"] == "Latest cover letter"


def _project(title: str) -> ProjectNotice:
    return ProjectNotice(
        source_message_id="m1",
        title=title,
        project_url=None,
        description=title,
        raw_text=title,
        project_key=title.lower().replace(" ", "-"),
    )
