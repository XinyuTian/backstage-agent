from datetime import date
from types import SimpleNamespace

from backstage_agent.agent import BackstageAgent
from backstage_agent.candidate_models import CandidateFeatures
from backstage_agent.models import CastingNotice, ProjectNotice
from backstage_agent.scoring import load_scoring_rules


class FakeEmailClient:
    def fetch_messages(self, limit, days, target_date=None):
        return [object()]


class FakeStore:
    def __init__(self):
        self.candidates = []
        self.refreshed_projects = []
        self.refreshed_roles = []
        self.existing_candidate_rows = []

    def upsert_project(self, project, seen_date):
        self.refreshed_projects.append(project)
        return 1

    def update_project_info(self, project_id, shooting_locations, shooting_dates):
        return None

    def upsert_role(self, project_id, notice):
        self.refreshed_roles.append(notice)
        return 1

    def record_candidate(self, candidate, features, requirement_matches, score):
        self.candidates.append((candidate, features, requirement_matches, score))
        return len(self.candidates)

    def candidate_rescore_sources_for_date(self, target_date):
        if not self.refreshed_projects:
            return []
        return [
            (
                self.refreshed_projects[-1],
                [(1, role) for role in self.refreshed_roles],
                1,
            )
        ]

    def candidate_rows_for_date(self, target_date):
        return self.existing_candidate_rows

    def clear_candidates_for_date(self, target_date):
        raise AssertionError("daily scan must not overwrite candidates")

    def update_candidate_rank(self, candidate_id, rank_position, rank_score):
        return None


class FakeFeatureExtractor:
    def extract(self, candidate):
        return CandidateFeatures(
            role_type="scripted_acting",
            project_type="theater",
            requirements={},
            project_signals={"career_goal_alignment": "high", "has_public_performance": True},
            compensation={"type": "paid", "amount_known": True},
            uncertainty={"compensation_missing": False, "role_details_sparse": False},
            evidence_snippets=["Evidence"],
        )


def _agent():
    agent = object.__new__(BackstageAgent)
    agent.email_client = FakeEmailClient()
    agent.store = FakeStore()
    agent.project_pages = SimpleNamespace(fetch_html=lambda url: "<html></html>")
    agent.profile = SimpleNamespace(union_status="non-union", skills=[], attributes={})
    agent.feature_extractor = FakeFeatureExtractor()
    agent.scoring_rules = load_scoring_rules()
    return agent


def _notice(role_key: str) -> CastingNotice:
    return CastingNotice(
        source_message_id="m1",
        title="Project - Lead",
        project="Project",
        role="Lead",
        location="Los Angeles",
        compensation="$100",
        role_key=role_key,
        description="Lead role",
        application_url="https://example.com/apply",
        raw_text="Lead role",
        shooting_locations="Los Angeles",
        shooting_dates="July 2026",
    )


def _project() -> ProjectNotice:
    return ProjectNotice(
        source_message_id="m1",
        title="Project",
        project_url="https://example.com",
        description="Project",
        raw_text="Project",
        project_key="project-key",
    )


def test_scan_refreshes_and_scores_without_legacy_services(monkeypatch):
    from backstage_agent import agent as agent_module

    backstage_agent = _agent()
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [_project()])
    monkeypatch.setattr(
        agent_module,
        "parse_project_page_roles",
        lambda project, html: [_notice("role-scored")],
    )

    result = backstage_agent.scan(limit=1, days=1, target_date=date(2026, 7, 24))

    for name in ("project_screener", "screener", "reviewer", "applications"):
        assert not hasattr(backstage_agent, name)
    assert len(backstage_agent.store.refreshed_projects) == 1
    assert len(backstage_agent.store.refreshed_roles) == 1
    assert result.candidates_scored == 1
    assert result.candidates_skipped_existing == 0
    assert result.notices_seen == 1
    assert set(result.__dataclass_fields__) == {
        "messages_seen",
        "projects_seen",
        "notices_seen",
        "candidates_scored",
        "candidates_skipped_existing",
        "draft_suggestions",
    }


def test_scan_preserves_existing_candidate_scores(monkeypatch):
    from backstage_agent import agent as agent_module

    backstage_agent = _agent()
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [_project()])
    monkeypatch.setattr(
        agent_module,
        "parse_project_page_roles",
        lambda project, html: [_notice("role-existing")],
    )
    backstage_agent.store.existing_candidate_rows = [
        {
            "id": 7,
            "candidate_type": "role",
            "project_key": "project-key",
            "role_key": "role-existing",
            "overall_score": 88,
            "score_band": "strong_candidate",
            "score_json": (
                '{"subscores":{},"score_caps":[],"positive_drivers":[],'
                '"negative_drivers":[],"score_trace":{}}'
            ),
            "rank_score": 88,
            "rank_position": 1,
            "draft_suggestion": 1,
            "scoring_version": "v1",
        }
    ]

    result = backstage_agent.scan(limit=1, days=1, target_date=date(2026, 7, 24))

    assert result.candidates_scored == 0
    assert result.candidates_skipped_existing == 1
    assert result.draft_suggestions == 1
    assert backstage_agent.store.candidates == []
