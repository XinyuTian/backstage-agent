# Module Guide

Use this guide to choose the smallest set of files to read for a task.

## CLI And Daily Operation

- Start with `src/backstage_agent/cli.py` for command behavior, scan summary JSON, notification triggering, dashboard startup, and login commands.
- Read `scripts/daily_scan.sh` and `launchd/com.sarahtxy.backstage-agent.daily.plist` for the daily run (9/10/11/12 local hours; retries when no email until noon give-up).
- Relevant tests: `tests/test_cli_summary.py`, plus module-specific tests for changed behavior.

## Configuration And Profile Data

- Start with `src/backstage_agent/settings.py` for environment variables and `.env` loading.
- Actor profile structure is in `src/backstage_agent/models.py` and example values are in `profile.example.json`.
- Avoid exposing real `profile.json` contents in docs, logs, or tests.

## Email And Parsing

- Start with `src/backstage_agent/email_client.py` for IMAP fetching, date filters, subject keywords, and MIME decoding.
- Use `src/backstage_agent/parser.py` for Backstage email digest parsing and fallback casting notice parsing.
- Use `src/backstage_agent/project_page_parser.py` when project-page HTML, embedded JSON, shooting dates, locations, or page-derived roles are involved.
- Relevant tests: `tests/test_email_client.py`, `tests/test_parser.py`, `tests/test_project_page_parser.py`.

## Screening And Review

- Start with `src/backstage_agent/agent.py` to understand the order of project gates, project reviews, role screening, role reviews, and applications.
- Use `src/backstage_agent/decision_core.py` for the five final buckets, structured model validation, reviewer downgrade policy, and reusable screening rules.
- Use `src/backstage_agent/project_screener.py` for project-level local checks and first-pass project LLM screening.
- Use `src/backstage_agent/screener.py` for role-level local checks and first-pass role LLM screening.
- Use `src/backstage_agent/reviewer.py` for downgrade-only reviewer behavior and reviewer provider calls.
- Relevant tests: `tests/test_decision_core.py`, `tests/test_structured_screening.py`, `tests/test_structured_reviewer.py`, `tests/test_agent_review_gate.py`, `tests/test_project_screener.py`, `tests/test_screener.py`.

## Application Drafting

- Start with `src/backstage_agent/application.py` for cover-note generation and dry-run/live-adapter guard behavior.
- Live Backstage submission is not implemented; `DRY_RUN=false` currently records `blocked_no_live_adapter`.
- Relevant tests: `tests/test_application.py`.

## Storage And Dashboard

- Start with `src/backstage_agent/storage.py` for SQLite schema, persistence, search filters, status counts, and lightweight migrations.
- Use `src/backstage_agent/ui.py` for dashboard rendering, filters, status labels, and application blocker display.
- Keep screening/review status distinct from application blocker state. Structured rows include final bucket, classifier JSON, reviewer JSON, reviewer impact, and schema errors.
- Relevant tests: `tests/test_storage_dashboard.py`, `tests/test_ui_labels.py`.

## Backstage Browser Access

- Start with `src/backstage_agent/browser_session.py` for Playwright persistent profile behavior, login checks, and authenticated HTML fetches.
- Use `src/backstage_agent/web_client.py` for the choice between direct HTTP and browser-backed fetching.
- Do not bypass login gates, Cloudflare challenges, CAPTCHA, or other access controls.

## Identifiers And De-Duplication

- Start with `src/backstage_agent/identifiers.py` for project and role key derivation.
- Storage duplicate checks live in `src/backstage_agent/storage.py`.
- Parser changes that affect titles, URLs, project dates, roles, or descriptions may affect de-duplication.
