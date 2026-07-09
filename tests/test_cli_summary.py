from backstage_agent.agent import ScanResult
from backstage_agent.cli import _scan_summary
from backstage_agent.models import CastingNotice, ReviewDecision, ScreeningDecision


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
    )


def test_scan_summary_includes_budget_warnings():
    first_pass_budget = ScreeningDecision(
        notice=_notice("First-pass Budget"),
        score=0.0,
        should_apply=False,
        reasons=[
            "Rejected because first-pass LLM screening was unavailable: no API key or call budget."
        ],
    )
    reviewer_budget_notice = _notice("Reviewer Budget")
    reviewer_budget = ScreeningDecision(
        notice=reviewer_budget_notice,
        score=0.8,
        should_apply=True,
        reasons=["Passed first pass."],
        llm_used=True,
    )
    result = ScanResult(
        messages_seen=1,
        projects_seen=1,
        notices_seen=2,
        project_decisions=[],
        project_reviews=[],
        decisions=[first_pass_budget, reviewer_budget],
        reviews=[
            ReviewDecision(
                notice=reviewer_budget_notice,
                status="error",
                score=0.0,
                reasons=["Reviewer unavailable: reviewer call budget was exhausted."],
            )
        ],
        applications=[],
    )

    summary = _scan_summary(result)

    assert "2 roles checked" in summary
    assert "Budget warning: 1 role-screening budget exhausted, 1 reviewer budget exhausted." in summary


def test_scan_summary_includes_project_layer_counts():
    project = ScreeningDecision(
        notice=_notice("Project Gate"),
        score=0.8,
        should_apply=True,
        reasons=["Passed project screening."],
        llm_used=True,
    )
    result = ScanResult(
        messages_seen=1,
        projects_seen=1,
        notices_seen=0,
        project_decisions=[project],
        project_reviews=[
            ReviewDecision(
                notice=project.notice,
                status="rejected",
                score=0.2,
                reasons=["Project reviewer found a conflict."],
            )
        ],
        decisions=[],
        reviews=[],
        applications=[],
    )

    summary = _scan_summary(result)

    assert "1 projects checked" in summary
    assert "0 project approved, 1 project need check, 0 project rejected" in summary
