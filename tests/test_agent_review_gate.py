from backstage_agent.agent import BackstageAgent
from backstage_agent.models import ReviewDecision, ScreeningDecision
from types import SimpleNamespace


class FakeEmailClient:
    def __init__(self, messages):
        self.messages = messages

    def fetch_messages(self, limit, days):
        return self.messages


class FakeStore:
    def __init__(self):
        self.decisions = []
        self.reviews = []
        self.applications = []

    def record_project(self, project):
        return 1

    def project_notice_exists(self, project):
        return False

    def role_exists(self, role_key):
        return False

    def decision_exists(self, role_key):
        return False

    def record_role(self, project_id, notice):
        return 1

    def record_decision(self, decision):
        self.decisions.append(decision)
        return len(self.decisions)

    def record_review(self, decision_id, review):
        self.reviews.append((decision_id, review))

    def record_application(self, draft):
        self.applications.append(draft)


class FakeApplications:
    def create_or_submit(self, decision):
        return object()


class FakeScreener:
    def __init__(self, should_apply):
        self.should_apply = should_apply

    def screen(self, notice):
        return ScreeningDecision(
            notice=notice,
            score=0.85 if self.should_apply else 0.0,
            should_apply=self.should_apply,
            reasons=["first pass"],
        )


class FakeReviewer:
    def __init__(self, status):
        self.status = status

    def review(self, notice):
        return ReviewDecision(
            notice=notice,
            status=self.status,
            score=0.9 if self.status == "approved" else 0.2,
            reasons=["review"],
        )


def _agent_with(notice, should_apply=True, reviewer_status="approved"):
    agent = object.__new__(BackstageAgent)
    agent.email_client = FakeEmailClient(messages=[object()])
    agent.store = FakeStore()
    agent.screener = FakeScreener(should_apply=should_apply)
    agent.reviewer = FakeReviewer(status=reviewer_status)
    agent.applications = FakeApplications()
    agent.project_pages = SimpleNamespace()
    return agent


def test_scan_applies_only_after_reviewer_approval(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = SimpleNamespace(role_key="role-approved")
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="approved")
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [SimpleNamespace(project_url="https://example.com")])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = backstage_agent.scan(limit=1, days=1)

    assert len(backstage_agent.store.reviews) == 1
    assert len(backstage_agent.store.applications) == 1
    assert len(result.applications) == 1


def test_scan_holds_conflict_without_application(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = SimpleNamespace(role_key="role-held")
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="rejected")
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [SimpleNamespace(project_url="https://example.com")])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = backstage_agent.scan(limit=1, days=1)

    assert len(backstage_agent.store.reviews) == 1
    assert len(backstage_agent.store.applications) == 0
    assert len(result.applications) == 0
