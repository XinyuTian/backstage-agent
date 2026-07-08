from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .application import ApplicationService
from .email_client import ImapEmailClient
from .models import ApplicationDraft, ScreeningDecision
from .parser import parse_project_notices
from .project_page_parser import parse_project_page_roles
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
    decisions: list[ScreeningDecision]
    applications: list[ApplicationDraft]


class BackstageAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.profile = load_actor_profile(settings.actor_profile_path)
        self.email_client = ImapEmailClient(settings)
        self.screener = RoleScreener(settings, self.profile)
        self.reviewer = DecisionReviewer(settings, self.profile)
        self.applications = ApplicationService(self.profile, settings.dry_run)
        self.store = DecisionStore(settings.database_path)
        self.project_pages = ProjectPageClient(settings)

    def scan(self, limit: int, days: int = 1, target_date: date | None = None) -> ScanResult:
        messages = self.email_client.fetch_messages(
            limit=limit,
            days=days,
            target_date=target_date,
        )
        decisions: list[ScreeningDecision] = []
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
            decisions=decisions,
            applications=application_drafts,
        )
