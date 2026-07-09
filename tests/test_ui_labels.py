import json

from backstage_agent.project_screener import PROJECT_GATE_ROLE
from backstage_agent.ui import _decision_status, _reviewer_detail, _screening_label


def _row(role=PROJECT_GATE_ROLE, **overrides):
    row = {
        "should_apply": 0,
        "application_status": None,
        "reviewer_status": None,
        "llm_used": 1,
        "reasons_json": '["Rejected by project LLM screening."]',
        "notice_json": json.dumps({"role": role}),
        "reviewer_reasons_json": None,
        "reviewer_concerns_json": None,
        "reviewer_score": None,
        "reviewer_model": None,
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
