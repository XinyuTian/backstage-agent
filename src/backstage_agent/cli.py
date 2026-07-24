from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from .agent import BackstageAgent
from .browser_session import BrowserSessionError, check_backstage_login, open_backstage_login
from .calibration import build_calibration_proposals
from .candidate_models import HumanFeedback
from .models import EmailMessage
from .notifier import send_mac_notification
from .parser import parse_casting_notices
from .settings import load_actor_profile, load_settings
from .storage import DecisionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="backstage-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Scan Backstage emails and screen roles")
    scan_parser.add_argument("--limit", type=int, default=25)
    scan_parser.add_argument("--days", type=int, default=1, help="Only scan emails from this many days back")
    scan_parser.add_argument("--date", help="Scan one exact local date, formatted YYYY-MM-DD")
    scan_parser.add_argument("--notify", action="store_true", help="Send a macOS notification when done")

    sample_parser = subparsers.add_parser("parse-sample", help="Parse a saved email text/html file")
    sample_parser.add_argument("path", type=Path)

    candidates_parser = subparsers.add_parser("candidates", help="Show ranked scored candidates")
    candidates_parser.add_argument("--limit", type=int, default=50)
    candidates_parser.add_argument("--band", default="all")
    candidates_parser.add_argument("--q", default="")

    feedback_parser = subparsers.add_parser("candidate-feedback", help="Record human scoring feedback")
    feedback_parser.add_argument("candidate_id", type=int)
    feedback_parser.add_argument("--human-score", type=int, required=True)
    feedback_parser.add_argument("--affected-components", required=True)
    feedback_parser.add_argument("--failure-modes", required=True)
    feedback_parser.add_argument("--reason", required=True)

    subparsers.add_parser("calibration-patterns", help="Show grouped feedback patterns")

    rescore_parser = subparsers.add_parser(
        "rescore-candidates",
        help="Rebuild candidate scores from stored projects and roles for one date",
    )
    rescore_parser.add_argument("--date", required=True, help="Project date to rebuild, formatted YYYY-MM-DD")

    score_parser = subparsers.add_parser(
        "score-candidates",
        help="Score stored candidates for one date without replacing existing scores",
    )
    score_parser.add_argument("--date", required=True, help="Project date, formatted YYYY-MM-DD")
    score_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete and rebuild existing candidate scores for the date",
    )

    subparsers.add_parser("show-config", help="Show resolved non-secret configuration")

    subparsers.add_parser(
        "backstage-login",
        help="Open a persistent browser profile so you can log in to Backstage once",
    )
    subparsers.add_parser(
        "backstage-login-check",
        help="Check whether the persistent Backstage browser profile is logged in",
    )

    ui_parser = subparsers.add_parser("ui", help="Run the local candidate UI")
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "scan":
        _scan(args.limit, args.days, args.date, args.notify)
    elif args.command == "parse-sample":
        _parse_sample(args.path)
    elif args.command == "candidates":
        _candidates(args.limit, args.band, args.q)
    elif args.command == "candidate-feedback":
        settings = load_settings()
        try:
            feedback_id = _record_feedback_from_args(DecisionStore(settings.database_path), args)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"feedback_id": feedback_id}, indent=2))
    elif args.command == "calibration-patterns":
        _calibration_patterns()
    elif args.command == "rescore-candidates":
        settings = load_settings()
        print(_rescore_candidates_for_date(args.date, settings=settings))
    elif args.command == "score-candidates":
        settings = load_settings()
        print(_score_candidates_for_date(args.date, args.overwrite, settings=settings))
    elif args.command == "show-config":
        _show_config()
    elif args.command == "backstage-login":
        _backstage_login()
    elif args.command == "backstage-login-check":
        _backstage_login_check()
    elif args.command == "ui":
        from .ui import DashboardServer

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
                "candidates_scored": result.candidates_scored,
                "candidates_skipped_existing": result.candidates_skipped_existing,
                "draft_suggestions": result.draft_suggestions,
                "days": days,
                "date": target_date.isoformat() if target_date else None,
                "summary": summary,
            },
            indent=2,
        )
    )
    if notify:
        send_mac_notification("Backstage Agent done", summary)


def _scan_summary(result) -> str:
    draft_label = "draft suggestion" if result.draft_suggestions == 1 else "draft suggestions"
    return (
        f"{result.projects_seen} projects refreshed, "
        f"{result.notices_seen} roles refreshed. "
        f"Candidates: {result.candidates_scored} scored, "
        f"{result.candidates_skipped_existing} existing skipped, "
        f"{result.draft_suggestions} {draft_label}."
    )


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


def _candidates(limit: int, band: str, query: str) -> None:
    settings = load_settings()
    print(_candidate_rows_json(DecisionStore(settings.database_path), limit=limit, band=band, query=query))


def _candidate_rows_json(
    store: DecisionStore,
    limit: int = 50,
    band: str = "all",
    query: str = "",
) -> str:
    rows = store.search_candidates(query=query, band=band, limit=limit)
    return json.dumps(
        [
            {
                "id": row["id"],
                "rank_position": row["rank_position"],
                "title": row["title"],
                "overall_score": row["overall_score"],
                "score_band": row["score_band"],
                "draft_suggestion": bool(row["draft_suggestion"]),
            }
            for row in rows
        ],
        indent=2,
    )


def _record_feedback_from_args(store: DecisionStore, args: Any) -> int:
    candidate_row = _candidate_row_by_id(store, args.candidate_id)
    feedback = HumanFeedback(
        candidate_id=args.candidate_id,
        agent_score=candidate_row["overall_score"],
        human_score=args.human_score,
        affected_components=_required_csv("affected_components", args.affected_components),
        failure_modes=_required_csv("failure_modes", args.failure_modes),
        free_text_reason=args.reason,
    )
    return store.record_candidate_feedback(feedback)


def _calibration_patterns() -> None:
    settings = load_settings()
    store = DecisionStore(settings.database_path)
    proposals = build_calibration_proposals(store.feedback_patterns())
    for proposal in proposals:
        store.record_calibration_proposal(proposal)
    print(
        json.dumps(
            [
                {
                    "pattern_key": proposal.pattern_key,
                    "example_count": proposal.example_count,
                    "average_delta": proposal.average_delta,
                    "affected_component": proposal.affected_component,
                    "failure_mode": proposal.failure_mode,
                    "proposal_text": proposal.proposal_text,
                    "status": proposal.status,
                }
                for proposal in proposals
            ],
            indent=2,
        )
    )


def _rescore_candidates_for_date(target_date_text: str, settings=None) -> str:
    return _score_candidates_for_date(target_date_text, overwrite=True, settings=settings)


def _score_candidates_for_date(
    target_date_text: str,
    overwrite: bool = False,
    settings=None,
) -> str:
    settings = settings or load_settings()
    target_date = date.fromisoformat(target_date_text)
    result = BackstageAgent(settings).score_candidates_for_date(
        target_date,
        overwrite=overwrite,
    )
    return json.dumps(
        {
            "date": result.date.isoformat(),
            "overwrite": result.overwrite,
            "candidates_scored": result.candidates_scored,
            "candidates_skipped_existing": result.candidates_skipped_existing,
            "candidates_deleted": result.candidates_deleted,
        },
        indent=2,
    )


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _required_csv(field_name: str, value: str) -> list[str]:
    items = _csv(value)
    if items:
        return items
    raise ValueError(f"{field_name} must include at least one non-empty value.")


def _candidate_row_by_id(store: DecisionStore, candidate_id: int) -> Any:
    for row in store.search_candidates(limit=1000000):
        if row["id"] == candidate_id:
            return row
    raise ValueError(f"Candidate {candidate_id} was not found.")


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
                "actor_profile": profile.name,
                "database_path": str(settings.database_path),
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
