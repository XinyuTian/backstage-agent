from __future__ import annotations

from dataclasses import dataclass

from .application import ApplicationService
from .email_client import ImapEmailClient
from .models import ApplicationDraft, ScreeningDecision
from .parser import parse_project_notices
from .project_page_parser import parse_project_page_roles
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
        self.applications = ApplicationService(self.profile, settings.dry_run)
        self.store = DecisionStore(settings.database_path)
        self.project_pages = ProjectPageClient()

    def scan(self, limit: int, days: int = 1) -> ScanResult:
        messages = self.email_client.fetch_messages(limit=limit, days=days)
        decisions: list[ScreeningDecision] = []
        application_drafts: list[ApplicationDraft] = []
        projects_seen = 0
        notices_seen = 0

        for message in messages:
            projects = parse_project_notices(message)
            projects_seen += len(projects)
            notices = []
            for project in projects:
                project_id = self.store.record_project(project)
                html = self.project_pages.fetch_html(project.project_url)
                page_roles = parse_project_page_roles(project, html or "") if html else []
                for role in page_roles:
                    self.store.record_role(project_id, role)
                notices.extend(page_roles)

            notices_seen += len(notices)
            for notice in notices:
                decision = self.screener.screen(notice)
                self.store.record_decision(decision)
                decisions.append(decision)
                if decision.should_apply:
                    draft = self.applications.create_or_submit(decision)
                    self.store.record_application(draft)
                    application_drafts.append(draft)

        return ScanResult(
            messages_seen=len(messages),
            projects_seen=projects_seen,
            notices_seen=notices_seen,
            decisions=decisions,
            applications=application_drafts,
        )
