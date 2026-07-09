from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from dataclasses import fields
from datetime import date

from backstage_agent.application import ApplicationService
from backstage_agent.models import CastingNotice, ProjectNotice
from backstage_agent.notifier import send_mac_notification
from backstage_agent.project_screener import ProjectScreener
from backstage_agent.reviewer import DecisionReviewer
from backstage_agent.screener import RoleScreener
from backstage_agent.settings import load_actor_profile, load_settings
from backstage_agent.storage import DecisionStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Rerun screening from stored project and role rows.")
    parser.add_argument("--date", required=True, help="Project date to rescore, formatted YYYY-MM-DD")
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    target_date = date.fromisoformat(args.date)
    source_projects, source_roles = _load_source_rows(settings.database_path, target_date)

    store = DecisionStore(settings.database_path)
    profile = load_actor_profile(settings.actor_profile_path)
    project_screener = ProjectScreener(settings, profile)
    role_screener = RoleScreener(settings, profile)
    reviewer = DecisionReviewer(settings, profile)
    applications = ApplicationService(settings, profile)

    _delete_date_rows(settings.database_path, target_date)

    project_decisions = []
    project_reviews = []
    role_decisions = []
    role_reviews = []
    application_drafts = []
    roles_by_project_key = defaultdict(list)
    for role in source_roles:
        roles_by_project_key[role.project_key].append(role)

    for project in source_projects:
        project_id = store.record_project(project)
        project_decision = project_screener.screen(project)
        project_decision_id = store.record_decision(project_decision)
        project_decisions.append(project_decision)
        if not project_decision.should_apply:
            continue

        project_review = reviewer.review_project(project_decision.notice)
        store.record_review(project_decision_id, project_review)
        project_reviews.append(project_review)
        if not project_review.approved:
            continue

        for role in roles_by_project_key[project.project_key]:
            store.record_role(project_id, role)
            role_decision = role_screener.screen(role)
            role_decision_id = store.record_decision(role_decision)
            role_decisions.append(role_decision)
            if not role_decision.should_apply:
                continue

            role_review = reviewer.review(role)
            store.record_review(role_decision_id, role_review)
            role_reviews.append(role_review)
            if not role_review.approved:
                continue

            try:
                draft = applications.create_or_submit(role_decision)
            except Exception as exc:  # noqa: BLE001
                draft = applications.failed_attempt(
                    role_decision,
                    f"{exc.__class__.__name__}: {exc}",
                )
            store.record_application(draft)
            application_drafts.append(draft)

    summary = _summary(
        project_decisions,
        project_reviews,
        role_decisions,
        role_reviews,
        application_drafts,
    )
    print(
        json.dumps(
            {
                "date": target_date.isoformat(),
                "source_projects": len(source_projects),
                "source_roles": len(source_roles),
                "project_decisions": len(project_decisions),
                "project_reviews": len(project_reviews),
                "decisions": len(role_decisions),
                "reviews": len(role_reviews),
                "applications": len(application_drafts),
                "summary": summary,
            },
            indent=2,
        )
    )
    if args.notify:
        send_mac_notification("Backstage Agent done", summary)


def _load_source_rows(db_path, target_date: date) -> tuple[list[ProjectNotice], list[CastingNotice]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        project_rows = conn.execute(
            """
            SELECT source_message_id, title, project_url, description, raw_text, project_date,
                   project_key, shooting_locations, shooting_dates
            FROM projects
            WHERE date(COALESCE(project_date, created_at)) = date(?)
            ORDER BY id
            """,
            (target_date.isoformat(),),
        ).fetchall()
        role_rows = conn.execute(
            """
            SELECT notice_json, project_key
            FROM roles
            WHERE date(COALESCE(project_date, created_at)) = date(?)
            ORDER BY id
            """,
            (target_date.isoformat(),),
        ).fetchall()

    projects = [
        ProjectNotice(
            source_message_id=row["source_message_id"],
            title=row["title"],
            project_url=row["project_url"],
            description=row["description"],
            raw_text=row["raw_text"],
            project_date=_date_from_text(row["project_date"]),
            project_key=row["project_key"],
            shooting_locations=row["shooting_locations"],
            shooting_dates=row["shooting_dates"],
        )
        for row in project_rows
    ]
    roles = []
    casting_fields = {field.name for field in fields(CastingNotice)}
    for row in role_rows:
        data = json.loads(row["notice_json"])
        data = {key: value for key, value in data.items() if key in casting_fields}
        data["project_date"] = _date_from_text(data.get("project_date"))
        roles.append(CastingNotice(**data))
    return projects, roles


def _delete_date_rows(db_path, target_date: date) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            DELETE FROM applications
            WHERE title IN (
              SELECT title FROM decisions
              WHERE date(COALESCE(project_date, created_at)) = date(?)
            )
            """,
            (target_date.isoformat(),),
        )
        conn.execute(
            "DELETE FROM decisions WHERE date(COALESCE(project_date, created_at)) = date(?)",
            (target_date.isoformat(),),
        )
        conn.execute(
            "DELETE FROM roles WHERE date(COALESCE(project_date, created_at)) = date(?)",
            (target_date.isoformat(),),
        )
        conn.execute(
            "DELETE FROM projects WHERE date(COALESCE(project_date, created_at)) = date(?)",
            (target_date.isoformat(),),
        )


def _summary(
    project_decisions,
    project_reviews,
    role_decisions,
    role_reviews,
    application_drafts,
) -> str:
    project_rejected = sum(1 for decision in project_decisions if not decision.should_apply)
    project_passed_screening = len(project_decisions) - project_rejected
    project_approved = sum(1 for review in project_reviews if review.approved)
    project_needs_check = max(0, project_passed_screening - project_approved)
    role_rejected = sum(1 for decision in role_decisions if not decision.should_apply)
    role_passed_screening = len(role_decisions) - role_rejected
    approved = len(application_drafts)
    role_needs_check = max(0, role_passed_screening - approved)
    submitted = sum(1 for draft in application_drafts if draft.status == "submitted_backstage")
    blocked = sum(
        1
        for draft in application_drafts
        if draft.status not in {"drafted", "submitted_backstage"}
    )
    return (
        f"{len(project_decisions)} projects checked, {project_approved} project approved, "
        f"{project_needs_check} project need check, {project_rejected} project rejected. "
        f"{len(role_decisions)} roles checked, {approved} approved, {submitted} submitted, "
        f"{blocked} application blockers, {role_needs_check} need check, {role_rejected} rejected."
    )


def _date_from_text(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


if __name__ == "__main__":
    main()
