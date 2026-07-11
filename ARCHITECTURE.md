# Architecture

## System Overview

Backstage Agent is a CLI-first Python package under `src/backstage_agent`. It fetches Backstage casting notification emails, extracts project and role data, optionally enriches projects from Backstage pages, screens matches against a local actor profile, records all decisions in SQLite, and exposes a small local dashboard for review.

The system is intentionally conservative: the default is dry-run application drafting, not live submission.

## Main Workflow

1. `src/backstage_agent/cli.py` handles `scan` arguments and loads settings.
2. `BackstageAgent.scan()` in `src/backstage_agent/agent.py` fetches recent email messages from IMAP.
3. `parser.parse_project_notices()` extracts project-level notices from each email digest.
4. `DecisionStore` skips projects already seen by project key or title/date fallback.
5. `ProjectPageClient` fetches project-page HTML through normal HTTP or an authenticated Playwright browser profile when enabled.
6. `project_page_parser` extracts page context, shooting info, and role-level notices when page HTML is available.
7. `ProjectScreener` performs local project rejects or structured LLM project screening into a final bucket.
8. `DecisionReviewer.review_project()` performs downgrade-only structured project review.
9. Approved projects proceed to role-level screening through `RoleScreener`.
10. Auto-draft role buckets receive strict downgrade-only review through `DecisionReviewer.review()`.
11. Roles that remain `Auto Apply/Draft` after review are passed to `ApplicationService`, which drafts or blocks application attempts.
12. `DecisionStore` persists projects, roles, decisions, reviewer results, and application records.
13. The CLI prints a JSON summary and optionally sends a macOS notification.

## Module Responsibilities

- `cli.py`: command-line entry point and scan summary formatting.
- `settings.py`: `.env` loading, environment parsing, and actor profile loading.
- `models.py`: dataclasses shared across parsing, screening, review, storage, and application drafting.
- `agent.py`: high-level scan orchestration.
- `email_client.py`: IMAP search, fetch, date-window filtering, MIME decoding.
- `parser.py`: email digest and fallback casting notice parsing.
- `project_page_parser.py`: Backstage project-page role, shooting location, and shooting date extraction.
- `web_client.py`: unauthenticated HTTP project-page fetches and browser-backed authenticated fetch dispatch.
- `browser_session.py`: Playwright persistent profile login, login checks, and authenticated HTML fetches.
- `project_screener.py`: project-level local checks and first-pass project LLM screening.
- `screener.py`: role-level local checks and first-pass role LLM screening.
- `decision_core.py`: five bucket constants, structured LLM/reviewer validation, rules loading, and deterministic bucket resolution.
- `reviewer.py`: downgrade-only structured project and role reviewer LLM calls.
- `application.py`: cover-note generation and dry-run/live-adapter guard behavior.
- `storage.py`: SQLite schema creation, lightweight migrations, persistence, dashboard queries, and key backfills.
- `ui.py`: local HTTP dashboard rendering and filtering.
- `notifier.py`: macOS notification wrapper.
- `identifiers.py`: stable project and role key generation from Backstage URLs or deterministic fallbacks.

See `docs/module-guide.md` for task-oriented reading guidance.

## Entry Points

- Console script: `backstage-agent`, configured in `pyproject.toml`.
- Module command: `python3 -m backstage_agent.cli ...`.
- Package module entry: `python3 -m backstage_agent ...` through `src/backstage_agent/__main__.py`.
- Daily automation: `scripts/daily_scan.sh`, scheduled by `launchd/com.sarahtxy.backstage-agent.daily.plist`.
- Local dashboard: `python3 -m backstage_agent.cli ui`.

## Data Flow

Email message -> project notices -> optional project page HTML -> project screening decision/bucket -> project review/bucket -> role notices -> role screening decision/bucket -> role review/bucket -> application draft/blocker -> SQLite rows -> CLI summary/dashboard.

Project-level decisions are stored in the same `decisions` table as role-level decisions, using the sentinel role value from `PROJECT_GATE_ROLE`.

## State and Storage

SQLite is the main durable state store. By default it is `backstage_agent.sqlite3`, controlled by `DATABASE_PATH`.

Main tables:

- `projects`: parsed project notices, project keys, page-derived shooting info.
- `roles`: role notices associated with projects.
- `decisions`: project and role screening decisions, final buckets, structured classifier/reviewer JSON, reviewer impact, schema errors, serialized notice JSON, keys, shooting info.
- `applications`: draft/submission/blocker records, cover notes, dry-run flag, blocker reason.

Schema creation and lightweight migrations happen in `DecisionStore._ensure_schema()`. There is no separate migration framework.

Local files that may contain sensitive or machine-specific state include `.env`, `profile.json`, `backstage_agent.sqlite3`, `browser_profiles/`, and `logs/`.

## External Services and Integrations

- IMAP mailbox access, typically Gmail with an app password.
- OpenAI-compatible chat completion APIs for first-pass screening, strict review, and cover-note generation.
- Backstage public or authenticated project pages.
- Playwright Chromium/Chrome persistent profile for logged-in Backstage page fetches.
- macOS `osascript` for desktop notifications.
- `launchd` for the daily local schedule.

## Configuration

Configuration is loaded in `settings.py` from environment variables after `python-dotenv` reads `.env`.

Important variables include:

- IMAP: `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `EMAIL_SEARCH_QUERY`, `EMAIL_SUBJECT_KEYWORDS`.
- LLM screening: `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY`, `AI_BUILDER_API_KEY`, `AI_BUILDER_BASE_URL`, `MAX_LLM_CALLS_PER_SCAN`, `MIN_MATCH_SCORE`.
- Reviewer and cover notes: `REVIEWER_PROVIDER`, `REVIEWER_MODEL`, `MAX_REVIEWER_CALLS_PER_SCAN`.
- Local state: `ACTOR_PROFILE_PATH`, `DATABASE_PATH`, `DRY_RUN`.
- Browser-backed Backstage access: `BACKSTAGE_BROWSER_PROFILE_PATH`, `USE_BROWSER_FOR_BACKSTAGE`, `BACKSTAGE_BROWSER_HEADLESS`, `BACKSTAGE_BROWSER_CHANNEL`.

## Architectural Constraints

- Preserve dry-run safety and explicit blocker behavior until live submission is deliberately implemented and verified.
- Keep project screening, role screening, reviewer status, and application blockers as separate concepts.
- Keep the daily automation optimized for one-day scans and macOS notification.
- Do not store Backstage passwords; use the persistent browser profile for session cookies.
- Avoid broad schema churn unless it is clearly needed; storage currently relies on inline schema creation and migration.
- Prefer tests around parsers, screeners, storage queries, and CLI summaries when behavior changes.
