from backstage_agent.agent import ScanResult
from backstage_agent.cli import _scan_summary


def _result(**overrides) -> ScanResult:
    values = {
        "messages_seen": 1,
        "projects_seen": 2,
        "notices_seen": 3,
        "project_decisions": [],
        "project_reviews": [],
        "decisions": [],
        "reviews": [],
        "applications": [],
        "candidates_scored": 3,
        "candidates_skipped_existing": 2,
        "draft_suggestions": 1,
    }
    values.update(overrides)
    return ScanResult(**values)


def test_scan_summary_reports_scoring_cutover():
    assert _scan_summary(_result()) == (
        "2 projects refreshed, 3 roles refreshed. "
        "Candidates: 3 scored, 2 existing skipped, 1 draft suggestion."
    )


def test_scan_summary_reports_zero_scoring_counts():
    assert _scan_summary(
        _result(
            messages_seen=0,
            projects_seen=0,
            notices_seen=0,
            candidates_scored=0,
            candidates_skipped_existing=0,
            draft_suggestions=0,
        )
    ) == (
        "0 projects refreshed, 0 roles refreshed. "
        "Candidates: 0 scored, 0 existing skipped, 0 draft suggestions."
    )
