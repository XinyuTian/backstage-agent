from backstage_agent.agent import BackstageAgent
from backstage_agent.candidate_models import CandidateFeatures
from backstage_agent.models import CastingNotice, ProjectNotice, ReviewDecision, ScreeningDecision
from backstage_agent.scoring import load_scoring_rules
from datetime import date
from types import SimpleNamespace


class FakeEmailClient:
    def __init__(self, messages):
        self.messages = messages

    def fetch_messages(self, limit, days, target_date=None):
        return self.messages


class FakeStore:
    def __init__(self):
        self.decisions = []
        self.reviews = []
        self.applications = []
        self.candidates = []
        self.refreshed_projects = []
        self.refreshed_roles = []
        self.existing_candidate_rows = []

    def record_project(self, project):
        return 1

    def upsert_project(self, project, seen_date):
        self.refreshed_projects.append(project)
        return 1

    def update_project_info(self, project_id, shooting_locations, shooting_dates):
        return None

    def project_notice_exists(self, project):
        return False

    def role_exists(self, role_key):
        return False

    def decision_exists(self, role_key):
        return False

    def record_role(self, project_id, notice):
        return 1

    def upsert_role(self, project_id, notice):
        self.refreshed_roles.append(notice)
        return 1

    def record_decision(self, decision):
        self.decisions.append(decision)
        return len(self.decisions)

    def record_review(self, decision_id, review):
        self.reviews.append((decision_id, review))

    def update_decision_artifacts(self, *args, **kwargs):
        return None

    def record_application(self, draft):
        self.applications.append(draft)

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


class FakeApplications:
    def create_or_submit(self, decision):
        return object()


class FakeScreener:
    def __init__(self, should_apply, final_bucket=None):
        self.should_apply = should_apply
        self.final_bucket = final_bucket

    def screen(self, notice):
        return ScreeningDecision(
            notice=notice,
            score=0.85 if self.should_apply else 0.0,
            should_apply=self.should_apply,
            reasons=["first pass"],
            final_bucket=self.final_bucket,
            classifier_json={"role_type": "scripted_acting"} if self.final_bucket else None,
        )


class FakeReviewer:
    def __init__(
        self,
        status,
        final_bucket=None,
        project_status="approved",
        project_final_bucket=None,
    ):
        self.status = status
        self.final_bucket = final_bucket
        self.project_status = project_status
        self.project_final_bucket = project_final_bucket
        self.initial_buckets = []

    def review_project(self, notice, initial_bucket=None, classifier_json=None):
        self.initial_buckets.append(initial_bucket)
        return ReviewDecision(
            notice=notice,
            status=self.project_status,
            score=0.9 if self.project_status == "approved" else 0.2,
            reasons=["project review"],
            final_bucket=self.project_final_bucket or initial_bucket,
        )

    def review(self, notice, initial_bucket=None, classifier_json=None):
        self.initial_buckets.append(initial_bucket)
        return ReviewDecision(
            notice=notice,
            status=self.status,
            score=0.9 if self.status == "approved" else 0.2,
            reasons=["review"],
            final_bucket=self.final_bucket or initial_bucket,
            reviewer_impact="downgraded" if self.final_bucket else "confirmed",
        )


def _agent_with(
    notice,
    should_apply=True,
    reviewer_status="approved",
    final_bucket=None,
    review_bucket=None,
    project_review_status="approved",
    project_review_bucket=None,
):
    agent = object.__new__(BackstageAgent)
    agent.email_client = FakeEmailClient(messages=[object()])
    agent.store = FakeStore()
    agent.project_screener = FakeScreener(should_apply=True, final_bucket="auto_apply_draft")
    agent.screener = FakeScreener(should_apply=should_apply, final_bucket=final_bucket)
    agent.reviewer = FakeReviewer(
        status=reviewer_status,
        final_bucket=review_bucket,
        project_status=project_review_status,
        project_final_bucket=project_review_bucket,
    )
    agent.applications = FakeApplications()
    agent.project_pages = SimpleNamespace()
    agent.profile = SimpleNamespace(
        union_status="non-union",
        skills=[],
        attributes={},
    )
    agent.feature_extractor = FakeFeatureExtractor()
    agent.scoring_rules = load_scoring_rules()
    return agent


def test_scan_refreshes_and_scores_without_legacy_execution(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = CastingNotice(
        source_message_id="m1",
        title="Project - Lead",
        project="Project",
        role="Lead",
        location="Los Angeles",
        compensation="$100",
        role_key="role-scored",
        description="Lead role",
        application_url="https://example.com/apply",
        raw_text="Lead role",
        shooting_locations="Los Angeles",
        shooting_dates="July 2026",
    )
    project = ProjectNotice(
        source_message_id="m1",
        title="Project",
        project_url="https://example.com",
        description="Project",
        raw_text="Project",
        project_key="project-key",
    )
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="approved")
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"
    backstage_agent.project_screener.screen = lambda notice: (_ for _ in ()).throw(
        AssertionError("legacy project screening ran")
    )
    backstage_agent.screener.screen = lambda notice: (_ for _ in ()).throw(
        AssertionError("legacy role screening ran")
    )
    backstage_agent.reviewer.review_project = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("legacy project review ran")
    )
    backstage_agent.reviewer.review = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("legacy role review ran")
    )
    backstage_agent.applications.create_or_submit = lambda decision: (_ for _ in ()).throw(
        AssertionError("legacy application drafting ran")
    )

    result = backstage_agent.scan(limit=1, days=1, target_date=date(2026, 7, 23))

    assert len(backstage_agent.store.refreshed_projects) == 1
    assert len(backstage_agent.store.refreshed_roles) == 1
    assert result.candidates_scored == 1
    assert result.candidates_skipped_existing == 0
    assert result.notices_seen == 1
    assert result.project_decisions == []
    assert result.project_reviews == []
    assert result.decisions == []
    assert result.reviews == []
    assert result.applications == []


def test_scan_preserves_existing_candidate_scores(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = CastingNotice(
        source_message_id="m1",
        title="Project - Lead",
        project="Project",
        role="Lead",
        location="Los Angeles",
        compensation="$100",
        role_key="role-existing",
        description="Lead role",
        application_url="https://example.com/apply",
        raw_text="Lead role",
        shooting_locations="Los Angeles",
        shooting_dates="July 2026",
    )
    project = ProjectNotice(
        source_message_id="m1",
        title="Project",
        project_url="https://example.com",
        description="Project",
        raw_text="Project",
        project_key="project-key",
    )
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="approved")
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"
    backstage_agent.store.existing_candidate_rows = [
        {
            "id": 7,
            "candidate_type": "role",
            "project_key": "project-key",
            "role_key": "role-existing",
            "overall_score": 88,
            "score_band": "strong_candidate",
            "subscores_json": "{}",
            "score_json": (
                '{"score_caps":[],"positive_drivers":[],"negative_drivers":[],'
                '"score_trace":{},"draft_suggestion":true,"scoring_version":"v1"}'
            ),
            "rank_score": 88,
            "rank_position": 1,
            "draft_suggestion": 1,
            "scoring_version": "v1",
        }
    ]

    result = backstage_agent.scan(limit=1, days=1, target_date=date(2026, 7, 23))

    assert result.candidates_scored == 0
    assert result.candidates_skipped_existing == 1
    assert result.draft_suggestions == 1
    assert backstage_agent.store.candidates == []
