import json

from backstage_agent.models import ApplicationDraft
from backstage_agent.models import ScreeningDecision
from backstage_agent.project_screener import PROJECT_GATE_ROLE
from backstage_agent.storage import DecisionStore
from backstage_agent.ui import (
    _decision_status,
    _generate_cover_letter_for_row,
    _render_detail,
    _reviewer_detail,
    _screening_label,
)


def _row(role=PROJECT_GATE_ROLE, **overrides):
    row = {
        "id": 42,
        "created_at": "2026-07-13 09:00:00",
        "project_date": "2026-07-13",
        "title": "Project - Role",
        "application_url": "https://example.com/apply",
        "score": 0.86,
        "should_apply": 0,
        "application_status": None,
        "application_blocker_reason": None,
        "reviewer_status": None,
        "llm_used": 1,
        "concerns_json": "[]",
        "reasons_json": '["Rejected by project LLM screening."]',
        "notice_json": json.dumps({"role": role}),
        "reviewer_reasons_json": None,
        "reviewer_concerns_json": None,
        "reviewer_score": None,
        "reviewer_model": None,
        "final_bucket": None,
        "classifier_json": None,
        "reviewer_json": None,
        "reviewer_impact": None,
        "shooting_locations": None,
        "shooting_dates": None,
        "cover_note": None,
    }
    row.update(overrides)
    return row


def test_project_llm_screening_rejection_label_is_project_rejected():
    row = _row(should_apply=0, llm_used=1)

    assert _decision_status(row) == ("Project Rejected", "reject")
    assert _screening_label(row) == "Project LLM screening"
    assert "project screening rejected it" in _reviewer_detail(row)


def test_project_reviewer_rejection_label_is_project_needs_check():
    row = _row(
        should_apply=1,
        reviewer_status="rejected",
        reviewer_score=0.2,
        reviewer_reasons_json='["Project reviewer found a conflict."]',
    )

    assert _decision_status(row) == ("Project Needs Check", "hold")
    assert _screening_label(row) == "Project LLM screening"


def test_role_screening_rejection_label_stays_role_rejected():
    row = _row(role="Role", should_apply=0, llm_used=False)

    assert _decision_status(row) == ("Rejected", "reject")
    assert _screening_label(row) == "Role local rejection"
    assert "role screening rejected it" in _reviewer_detail(row)


def test_role_detail_includes_cover_letter_action_at_bottom():
    row = _row(
        role="Lead",
        should_apply=1,
        reviewer_status="approved",
        final_bucket="auto_apply_draft",
        notice_json=json.dumps({"role": "Lead", "description": "Lead role"}),
        reasons_json='["Strong fit."]',
    )

    html = _render_detail(row)

    assert 'action="/cover-letter"' in html
    assert 'name="decision_id" value="42"' in html
    assert "Generate Cover Letter" in html
    assert html.rfind("Generate Cover Letter") > html.rfind("Parsed Notice")


def test_project_gate_detail_omits_cover_letter_action():
    row = _row(
        should_apply=1,
        reviewer_status="approved",
        final_bucket="auto_apply_draft",
        notice_json=json.dumps({"role": PROJECT_GATE_ROLE, "description": "Project gate"}),
        reasons_json='["Project passed."]',
    )

    html = _render_detail(row)

    assert "Generate Cover Letter" not in html
    assert 'action="/cover-letter"' not in html


def test_role_detail_renders_cover_letter():
    row = _row(
        role="Lead",
        should_apply=1,
        reviewer_status="approved",
        final_bucket="auto_apply_draft",
        notice_json=json.dumps({"role": "Lead", "description": "Lead role"}),
        reasons_json='["Strong fit."]',
        cover_note="Dear Casting Team,\n\nI would love to be considered.",
    )

    html = _render_detail(row)

    assert "<h3>Cover Letter</h3>" in html
    assert "Dear Casting Team," in html
    assert "I would love to be considered." in html


def test_generate_cover_letter_for_row_records_draft(
    tmp_path,
    settings_factory,
    actor_profile_factory,
    monkeypatch,
):
    settings = settings_factory(database_path=tmp_path / "db.sqlite3")
    store = DecisionStore(settings.database_path)
    notice = {
        "source_message_id": "m1",
        "title": "Play - Lead",
        "project": "Play",
        "role": "Lead",
        "location": "Los Angeles",
        "compensation": "$100",
        "description": "Lead role",
        "application_url": "https://example.com/apply",
        "raw_text": "Lead role",
    }
    row = _row(
        role="Lead",
        notice_json=json.dumps(notice),
        reasons_json='["Strong fit."]',
        concerns_json="[]",
    )
    store.record_decision(
        ScreeningDecision(
            notice=_decision_from_notice(notice),
            score=0.86,
            should_apply=True,
            reasons=["Strong fit."],
            final_bucket="auto_apply_draft",
        )
    )

    class FakeApplicationService:
        def __init__(self, received_settings, profile):
            self.received_settings = received_settings
            self.profile = profile

        def generate_cover_letter(self, decision):
            return ApplicationDraft(
                notice=decision.notice,
                cover_note=f"Cover letter for {decision.notice.title}",
                dry_run=True,
                status="drafted",
            )

    monkeypatch.setattr("backstage_agent.ui.load_actor_profile", lambda path: actor_profile_factory())
    monkeypatch.setattr("backstage_agent.ui.ApplicationService", FakeApplicationService)

    _generate_cover_letter_for_row(row, settings, store)

    rows = store.search_decisions(query="Play")
    assert rows[0]["cover_note"] == "Cover letter for Play - Lead"
    assert rows[0]["application_status"] == "drafted"


def _decision_from_notice(notice):
    from backstage_agent.models import CastingNotice

    return CastingNotice(**notice)
