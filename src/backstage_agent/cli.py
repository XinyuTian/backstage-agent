from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .agent import BackstageAgent
from .browser_session import BrowserSessionError, check_backstage_login, open_backstage_login
from .models import EmailMessage
from .notifier import send_mac_notification
from .parser import parse_casting_notices
from .settings import load_actor_profile, load_settings
from .storage import DecisionStore
from .ui import DashboardServer


def main() -> None:
    parser = argparse.ArgumentParser(prog="backstage-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan Backstage emails and screen roles")
    scan_parser.add_argument("--limit", type=int, default=25)
    scan_parser.add_argument("--days", type=int, default=1, help="Only scan emails from this many days back")
    scan_parser.add_argument("--date", help="Scan one exact local date, formatted YYYY-MM-DD")
    scan_parser.add_argument("--notify", action="store_true", help="Send a macOS notification when done")

    sample_parser = subparsers.add_parser("parse-sample", help="Parse a saved email text/html file")
    sample_parser.add_argument("path", type=Path)

    decisions_parser = subparsers.add_parser("decisions", help="Show recent screening decisions")
    decisions_parser.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("show-config", help="Show resolved non-secret configuration")

    subparsers.add_parser(
        "backstage-login",
        help="Open a persistent browser profile so you can log in to Backstage once",
    )
    subparsers.add_parser(
        "backstage-login-check",
        help="Check whether the persistent Backstage browser profile is logged in",
    )

    ui_parser = subparsers.add_parser("ui", help="Run a local decision search UI")
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.command == "scan":
        _scan(args.limit, args.days, args.date, args.notify)
    elif args.command == "parse-sample":
        _parse_sample(args.path)
    elif args.command == "decisions":
        _decisions(args.limit)
    elif args.command == "show-config":
        _show_config()
    elif args.command == "backstage-login":
        _backstage_login()
    elif args.command == "backstage-login-check":
        _backstage_login_check()
    elif args.command == "ui":
        DashboardServer(host=args.host, port=args.port).serve_forever()


def _scan(
    limit: int,
    days: int,
    target_date_text: str | None = None,
    notify: bool = False,
) -> None:
    settings = load_settings()
    target_date = date.fromisoformat(target_date_text) if target_date_text else None
    result = BackstageAgent(settings).scan(limit=limit, days=days, target_date=target_date)
    summary = _scan_summary(result)
    print(
        json.dumps(
            {
                "messages_seen": result.messages_seen,
                "projects_seen": result.projects_seen,
                "notices_seen": result.notices_seen,
                "project_decisions": len(result.project_decisions),
                "project_reviews": len(result.project_reviews),
                "decisions": len(result.decisions),
                "reviews": len(result.reviews),
                "applications": len(result.applications),
                "days": days,
                "date": target_date.isoformat() if target_date else None,
                "dry_run": settings.dry_run,
                "summary": summary,
            },
            indent=2,
        )
    )
    if notify:
        send_mac_notification("Backstage Agent done", summary)


def _scan_summary(result) -> str:
    project_rejected = sum(1 for decision in result.project_decisions if not decision.should_apply)
    project_passed_screening = len(result.project_decisions) - project_rejected
    project_approved = sum(1 for review in result.project_reviews if review.approved)
    project_needs_check = max(0, project_passed_screening - project_approved)
    rejected = sum(1 for decision in result.decisions if not decision.should_apply)
    first_passed = len(result.decisions) - rejected
    approved = len(result.applications)
    needs_check = max(0, first_passed - approved)
    submitted = sum(1 for app in result.applications if app.status == "submitted_backstage")
    blocked = sum(
        1
        for app in result.applications
        if app.status not in {"drafted", "submitted_backstage"}
    )
    summary = (
        f"{len(result.project_decisions)} projects checked, "
        f"{project_approved} project approved, {project_needs_check} project need check, "
        f"{project_rejected} project rejected. "
        f"{result.notices_seen} roles checked, {approved} approved, "
        f"{submitted} submitted, {blocked} application blockers, "
        f"{needs_check} need check, {rejected} rejected."
    )
    budget_warnings = _budget_warnings(result)
    return f"{summary} {budget_warnings}" if budget_warnings else summary


def _budget_warnings(result) -> str:
    project_screening_exhausted = sum(
        1
        for decision in result.project_decisions
        if any("project llm screening was unavailable" in reason.lower() for reason in decision.reasons)
    )
    first_pass_exhausted = sum(
        1
        for decision in result.decisions
        if any("first-pass llm screening was unavailable" in reason.lower() for reason in decision.reasons)
    )
    reviewer_exhausted = sum(
        1
        for review in [*result.project_reviews, *result.reviews]
        if any("reviewer call budget was exhausted" in reason.lower() for reason in review.reasons)
    )
    warnings = []
    if project_screening_exhausted:
        warnings.append(f"{project_screening_exhausted} project-screening budget exhausted")
    if first_pass_exhausted:
        warnings.append(f"{first_pass_exhausted} role-screening budget exhausted")
    if reviewer_exhausted:
        warnings.append(f"{reviewer_exhausted} reviewer budget exhausted")
    return "Budget warning: " + ", ".join(warnings) + "." if warnings else ""


def _parse_sample(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    message = EmailMessage(
        message_id=f"sample:{path.name}",
        subject=path.name,
        sender="sample",
        received_at=None,
        html=content if "<html" in content.lower() else "",
        text=content if "<html" not in content.lower() else "",
    )
    notices = parse_casting_notices(message)
    print(json.dumps([notice.__dict__ for notice in notices], indent=2))


def _decisions(limit: int) -> None:
    settings = load_settings()
    store = DecisionStore(settings.database_path)
    rows = store.recent_decisions(limit=limit)
    print(
        json.dumps(
            [
                {
                    "created_at": row["created_at"],
                    "title": row["title"],
                    "score": row["score"],
                    "should_apply": bool(row["should_apply"]),
                    "llm_used": bool(row["llm_used"]),
                    "reasons": json.loads(row["reasons_json"]),
                }
                for row in rows
            ],
            indent=2,
        )
    )


def _show_config() -> None:
    settings = load_settings()
    profile = load_actor_profile(settings.actor_profile_path)
    print(
        json.dumps(
            {
                "imap_host": settings.imap_host,
                "imap_port": settings.imap_port,
                "imap_username": settings.imap_username,
                "imap_folder": settings.imap_folder,
                "email_search_query": settings.email_search_query,
                "email_subject_keywords": settings.email_subject_keywords,
                "llm_provider": settings.llm_provider,
                "llm_model": settings.llm_model,
                "max_llm_calls_per_scan": settings.max_llm_calls_per_scan,
                "reviewer_provider": settings.reviewer_provider,
                "reviewer_model": settings.reviewer_model,
                "max_reviewer_calls_per_scan": settings.max_reviewer_calls_per_scan,
                "min_match_score": settings.min_match_score,
                "actor_profile": profile.name,
                "database_path": str(settings.database_path),
                "dry_run": settings.dry_run,
                "browser_profile_path": str(settings.browser_profile_path),
                "use_browser_for_backstage": settings.use_browser_for_backstage,
                "backstage_browser_headless": settings.backstage_browser_headless,
                "backstage_browser_channel": settings.backstage_browser_channel,
                "has_openai_api_key": settings.openai_api_key is not None,
                "has_ai_builder_api_key": settings.ai_builder_api_key is not None,
            },
            indent=2,
        )
    )


def _backstage_login() -> None:
    settings = load_settings()
    try:
        open_backstage_login(settings)
    except BrowserSessionError as exc:
        raise SystemExit(str(exc)) from exc


def _backstage_login_check() -> None:
    settings = load_settings()
    try:
        check = check_backstage_login(settings)
    except BrowserSessionError as exc:
        raise SystemExit(str(exc)) from exc
    print(
        json.dumps(
            {
                "logged_in": check.logged_in,
                "url": check.url,
                "title": check.title,
                "reason": check.reason,
                "browser_profile_path": str(settings.browser_profile_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
