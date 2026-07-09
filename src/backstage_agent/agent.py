from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .application import ApplicationService
from .email_client import ImapEmailClient
from .models import ApplicationDraft, ReviewDecision, ScreeningDecision
from .parser import parse_project_notices
from .project_page_parser import parse_project_page_roles
from .project_screener import ProjectScreener, with_project_shooting_info
from .reviewer import DecisionReviewer
from .screener import RoleScreener
from .settings import Settings, load_actor_profile
from .storage import DecisionStore
from .web_client import ProjectPageClient


@dataclass(frozen=True)
class ScanResult:
    messages_seen: int
    projects_seen: int
    notices_seen: int
    project_decisions: list[ScreeningDecision]
    project_reviews: list[ReviewDecision]
    decisions: list[ScreeningDecision]
    reviews: list[ReviewDecision]
    applications: list[ApplicationDraft]


class BackstageAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.profile = load_actor_profile(settings.actor_profile_path)
        self.email_client = ImapEmailClient(settings)
        self.project_screener = ProjectScreener(settings, self.profile)
        self.screener = RoleScreener(settings, self.profile)
        self.reviewer = DecisionReviewer(settings, self.profile)
        self.applications = ApplicationService(settings, self.profile)
        self.store = DecisionStore(settings.database_path)
        self.project_pages = ProjectPageClient(settings)

    def scan(self, limit: int, days: int = 1, target_date: date | None = None) -> ScanResult:
        messages = self.email_client.fetch_messages(
            limit=limit,
            days=days,
            target_date=target_date,
        )
        project_decisions: list[ScreeningDecision] = []
        project_reviews: list[ReviewDecision] = []
        decisions: list[ScreeningDecision] = []
        reviews: list[ReviewDecision] = []
        application_drafts: list[ApplicationDraft] = []
        projects_seen = 0
        notices_seen = 0

        for message in messages:
            projects = parse_project_notices(message)
            projects_seen += len(projects)
            notices = []
            for project in projects:
                if self.store.project_notice_exists(project):
                    continue
                project_id = self.store.record_project(project)
                html = self.project_pages.fetch_html(project.project_url)
                page_roles = parse_project_page_roles(project, html or "") if html else []
                if page_roles:
                    self.store.update_project_info(
                        project_id,
                        page_roles[0].shooting_locations,
                        page_roles[0].shooting_dates,
                    )
                    project = with_project_shooting_info(
                        project,
                        page_roles[0].shooting_locations,
                        page_roles[0].shooting_dates,
                    )
                project_decision = self.project_screener.screen(project)
                project_decision_id = self.store.record_decision(project_decision)
                project_decisions.append(project_decision)
                if not project_decision.should_apply:
                    continue
                project_review = self.reviewer.review_project(project_decision.notice)
                self.store.record_review(project_decision_id, project_review)
                project_reviews.append(project_review)
                if not project_review.approved:
                    continue
                for role in page_roles:
                    if self.store.role_exists(role.role_key) or self.store.decision_exists(role.role_key):
                        continue
                    self.store.record_role(project_id, role)
                    notices.append(role)

            notices_seen += len(notices)
            for notice in notices:
                decision = self.screener.screen(notice)
                decision_id = self.store.record_decision(decision)
                decisions.append(decision)
                if decision.should_apply:
                    review = self.reviewer.review(notice)
                    self.store.record_review(decision_id, review)
                    reviews.append(review)
                    if review.approved:
                        try:
                            draft = self.applications.create_or_submit(decision)
                        except Exception as exc:  # noqa: BLE001
                            draft = self.applications.failed_attempt(
                                decision,
                                f"{exc.__class__.__name__}: {exc}",
                            )
                        self.store.record_application(draft)
                        application_drafts.append(draft)

        return ScanResult(
            messages_seen=len(messages),
            projects_seen=projects_seen,
            notices_seen=notices_seen,
            project_decisions=project_decisions,
            project_reviews=project_reviews,
            decisions=decisions,
            reviews=reviews,
            applications=application_drafts,
        )
