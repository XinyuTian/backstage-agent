from __future__ import annotations

import argparse
import json
from pathlib import Path

from .agent import BackstageAgent
from .models import EmailMessage
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

    sample_parser = subparsers.add_parser("parse-sample", help="Parse a saved email text/html file")
    sample_parser.add_argument("path", type=Path)

    decisions_parser = subparsers.add_parser("decisions", help="Show recent screening decisions")
    decisions_parser.add_argument("--limit", type=int, default=20)

    subparsers.add_parser("show-config", help="Show resolved non-secret configuration")

    ui_parser = subparsers.add_parser("ui", help="Run a local decision search UI")
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.command == "scan":
        _scan(args.limit, args.days)
    elif args.command == "parse-sample":
        _parse_sample(args.path)
    elif args.command == "decisions":
        _decisions(args.limit)
    elif args.command == "show-config":
        _show_config()
    elif args.command == "ui":
        DashboardServer(host=args.host, port=args.port).serve_forever()


def _scan(limit: int, days: int) -> None:
    settings = load_settings()
    result = BackstageAgent(settings).scan(limit=limit, days=days)
    print(
        json.dumps(
            {
                "messages_seen": result.messages_seen,
                "projects_seen": result.projects_seen,
                "notices_seen": result.notices_seen,
                "decisions": len(result.decisions),
                "applications": len(result.applications),
                "days": days,
                "dry_run": settings.dry_run,
            },
            indent=2,
        )
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
                "llm_model": settings.llm_model,
                "max_llm_calls_per_scan": settings.max_llm_calls_per_scan,
                "reviewer_model": settings.reviewer_model,
                "max_reviewer_calls_per_scan": settings.max_reviewer_calls_per_scan,
                "min_match_score": settings.min_match_score,
                "actor_profile": profile.name,
                "database_path": str(settings.database_path),
                "dry_run": settings.dry_run,
                "has_openai_api_key": settings.openai_api_key is not None,
                "has_ai_builder_api_key": settings.ai_builder_api_key is not None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
