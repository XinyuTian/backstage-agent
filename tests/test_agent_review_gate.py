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


def test_scan_applies_only_after_reviewer_approval(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = CastingNotice(
        source_message_id="m1",
        title="Project - Lead",
        project="Project",
        role="Lead",
        location="Los Angeles",
        compensation="$100",
        role_key="role-approved",
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

    result = backstage_agent.scan(limit=1, days=1)

    assert len(backstage_agent.store.reviews) == 2
    assert len(result.project_reviews) == 1
    assert len(result.reviews) == 1
    assert len(backstage_agent.store.applications) == 1
    assert len(result.applications) == 1


def test_scan_holds_conflict_without_application(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = CastingNotice(
        source_message_id="m1",
        title="Project - Lead",
        project="Project",
        role="Lead",
        location="Los Angeles",
        compensation="$100",
        role_key="role-held",
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
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="rejected")
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = backstage_agent.scan(limit=1, days=1)

    assert len(backstage_agent.store.reviews) == 2
    assert len(result.project_reviews) == 1
    assert len(result.reviews) == 1
    assert len(backstage_agent.store.applications) == 0
    assert len(result.applications) == 0


def test_scan_does_not_draft_reviewer_downgraded_role(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = CastingNotice(
        source_message_id="m1",
        title="Project - Lead",
        project="Project",
        role="Lead",
        location="Los Angeles",
        compensation="$100",
        role_key="role-ready-review",
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
    backstage_agent = _agent_with(
        notice,
        should_apply=True,
        reviewer_status="hold",
        final_bucket="auto_apply_draft",
        review_bucket="ready_for_review",
    )
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = backstage_agent.scan(limit=1, days=1)

    assert "auto_apply_draft" in backstage_agent.reviewer.initial_buckets
    assert len(backstage_agent.store.applications) == 0
    assert len(result.applications) == 0


def test_scan_refreshes_repeated_project_without_running_candidate_scoring(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = CastingNotice(
        source_message_id="m1",
        title="Project - Lead",
        project="Project",
        role="Lead",
        location="Los Angeles",
        compensation="$100",
        role_key="role-project-held",
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
    backstage_agent = _agent_with(
        notice,
        should_apply=True,
        reviewer_status="approved",
        project_review_status="hold",
        project_review_bucket="ready_for_review",
    )
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"
    backstage_agent.feature_extractor = SimpleNamespace(
        extract=lambda candidate: (_ for _ in ()).throw(AssertionError("candidate scoring ran"))
    )

    result = backstage_agent.scan(limit=1, days=1, target_date=date(2026, 7, 15))

    assert len(backstage_agent.store.candidates) == 0
    assert result.candidates_scored == 0
    assert result.draft_suggestions == 0
    assert backstage_agent.store.refreshed_projects[0].source_message_id == "m1"
    assert backstage_agent.store.refreshed_roles[0].role_key == "role-project-held"
    assert len(backstage_agent.store.decisions) == 1
    assert len(result.decisions) == 0
    assert len(backstage_agent.store.applications) == 0
    assert len(result.applications) == 0
