import json
from datetime import date

from backstage_agent.candidate_models import HumanFeedback
from backstage_agent.agent import CandidateScoringResult
from backstage_agent.cli import (
    _calibration_patterns,
    _candidate_rows_json,
    _record_feedback_from_args,
    _rescore_candidates_for_date,
    _score_candidates_for_date,
)


class FakeStore:
    def __init__(self, rows=None):
        self.feedback = None
        self.rows = rows or [
            {
                "id": 1,
                "title": "Play - Lead",
                "overall_score": 86,
                "score_band": "strong_candidate",
                "draft_suggestion": 1,
                "rank_position": 1,
            }
        ]

    def search_candidates(self, query="", band="all", limit=200):
        return self.rows

    def record_candidate_feedback(self, feedback: HumanFeedback):
        self.feedback = feedback
        return 9


class FakeCalibrationStore:
    def __init__(self):
        self.proposals = {}

    def active_calibration_evidence(self):
        return [
            {
                "id": index,
                "candidate_type": "role",
                "project_key": f"project-{index}",
                "role_key": f"role-{index}",
                "component_name": "role_value",
                "target_kind": "component",
                "human_target": 5,
                "current_component_score": 15,
                "current_overall_score": 80,
                "current_scoring_version": "test-v2",
                "created_at": "2026-08-01 00:00:00",
            }
            for index in range(1, 4)
        ]

    def record_calibration_proposal_idempotent(self, proposal, evidence):
        key = (
            proposal.pattern_key,
            proposal.scoring_version,
            proposal.evidence_fingerprint,
        )
        created = key not in self.proposals
        if created:
            self.proposals[key] = len(self.proposals) + 1
        return self.proposals[key], created


def test_calibration_patterns_reports_idempotent_bootstrap_proposal():
    store = FakeCalibrationStore()

    first = json.loads(
        _calibration_patterns(
            store=store,
            rules={"version": "test-v2"},
            calibration_date=date(2026, 8, 4),
        )
    )
    second = json.loads(
        _calibration_patterns(
            store=store,
            rules={"version": "test-v2"},
            calibration_date=date(2026, 8, 4),
        )
    )

    assert first["proposals"][0]["created"] is True
    assert second["proposals"][0]["created"] is False
    assert first["proposals"][0]["maturity_stage"] == "bootstrap"
    assert first["proposals"][0]["proposed_adjustment"] == -5
    assert first["active_evidence_count"] == 3
    assert second["message"] == "No new calibration proposal was needed."


def test_candidate_rows_json_outputs_ranked_candidates():
    payload = json.loads(_candidate_rows_json(FakeStore(), limit=10))

    assert payload[0]["title"] == "Play - Lead"
    assert payload[0]["overall_score"] == 86
    assert payload[0]["draft_suggestion"] is True


def test_record_feedback_from_args_stores_taxonomy():
    class Args:
        candidate_id = 1
        human_score = 45
        affected_components = "identity_match"
        failure_modes = "overweighted_signal"
        reason = "Nationality over-weighted."

    store = FakeStore()
    feedback_id = _record_feedback_from_args(store, Args())

    assert feedback_id == 9
    assert store.feedback.score_delta == -41
    assert store.feedback.agent_score == 86
    assert store.feedback.affected_components == ["identity_match"]


def test_record_feedback_from_args_requires_existing_candidate():
    class Args:
        candidate_id = 99
        human_score = 45
        affected_components = "identity_match"
        failure_modes = "overweighted_signal"
        reason = "Nationality over-weighted."

    store = FakeStore(rows=[])

    try:
        _record_feedback_from_args(store, Args())
    except ValueError as exc:
        assert str(exc) == "Candidate 99 was not found."
    else:
        raise AssertionError("expected ValueError")


def test_record_feedback_from_args_rejects_blank_affected_components():
    class Args:
        candidate_id = 1
        human_score = 45
        affected_components = "   ,  "
        failure_modes = "overweighted_signal"
        reason = "Nationality over-weighted."

    store = FakeStore()

    try:
        _record_feedback_from_args(store, Args())
    except ValueError as exc:
        assert str(exc) == "affected_components must include at least one non-empty value."
    else:
        raise AssertionError("expected ValueError")

    assert store.feedback is None


def test_record_feedback_from_args_rejects_blank_failure_modes():
    class Args:
        candidate_id = 1
        human_score = 45
        affected_components = "identity_match"
        failure_modes = "   ,  "
        reason = "Nationality over-weighted."

    store = FakeStore()

    try:
        _record_feedback_from_args(store, Args())
    except ValueError as exc:
        assert str(exc) == "failure_modes must include at least one non-empty value."
    else:
        raise AssertionError("expected ValueError")

    assert store.feedback is None


def test_score_candidates_for_date_reports_safe_counts(monkeypatch):
    class FakeAgent:
        def __init__(self, settings):
            self.settings = settings

        def score_candidates_for_date(self, target_date, overwrite=False):
            return CandidateScoringResult(target_date, overwrite, 2, 3, 0)

    monkeypatch.setattr("backstage_agent.cli.BackstageAgent", FakeAgent)
    output = json.loads(
        _score_candidates_for_date("2026-07-15", overwrite=False, settings=object())
    )

    assert output == {
        "date": "2026-07-15",
        "overwrite": False,
        "candidates_scored": 2,
        "candidates_skipped_existing": 3,
        "candidates_deleted": 0,
    }


def test_rescore_candidates_for_date_uses_overwrite(monkeypatch):
    class FakeAgent:
        def __init__(self, settings):
            self.settings = settings

        def score_candidates_for_date(self, target_date, overwrite=False):
            assert overwrite is True
            return CandidateScoringResult(target_date, True, 4, 0, 2)

    monkeypatch.setattr("backstage_agent.cli.BackstageAgent", FakeAgent)
    output = json.loads(_rescore_candidates_for_date("2026-07-15", settings=object()))

    assert output["overwrite"] is True
    assert output["candidates_scored"] == 4
    assert output["candidates_deleted"] == 2
