# Project State

Last updated: 2026-07-10

This file represents the present state of the project. Edit it in place as functionality, priorities, blockers, or known issues change; do not use it as a historical log.

## Current Objective

Build a conservative local automation agent that scans daily Backstage casting emails, screens projects and roles against the actor profile, stores auditable decisions, and prepares application drafts without unsafe live submission.

## Current Capabilities

- CLI package `backstage-agent` / `python3 -m backstage_agent.cli` with commands for scanning, sample parsing, recent decisions, config display, dashboard serving, and persistent Backstage login checks.
- IMAP email ingestion in `src/backstage_agent/email_client.py`, defaulting to recent Backstage-related messages and supporting `--days` or an exact `--date`.
- Email digest parsing in `src/backstage_agent/parser.py` and optional Backstage project-page parsing in `src/backstage_agent/project_page_parser.py`.
- Two-layer screening flow in `src/backstage_agent/agent.py`: project gate, downgrade-only project review, role screening, downgrade-only role review, then application draft/blocker recording.
- Deterministic local screening checks plus structured first-pass LLM screening and reviewer validation through OpenAI-compatible clients.
- Five final decision buckets: `Auto Apply/Draft`, `Ready For Review`, `Needs My Preference`, `Reject`, and `Data/Parse Error`.
- SQLite persistence in `src/backstage_agent/storage.py` for projects, roles, decisions, final buckets, structured classifier/reviewer artifacts, reviews, applications, keys, shooting locations, and shooting dates.
- Local dashboard in `src/backstage_agent/ui.py` at `http://127.0.0.1:8765` for searching decisions, final buckets, reviewer impact, status details, and on-demand role cover-letter drafts.
- macOS notification helper in `src/backstage_agent/notifier.py` and daily launchd assets in `scripts/daily_scan.sh` and `launchd/com.sarahtxy.backstage-agent.daily.plist`.
- Dry-run application drafting in `src/backstage_agent/application.py`, including guarded cover-note generation.

## In Progress

- Parser and project-page extraction are being actively hardened against real Backstage digest/page variations.
- The daily scan path is present and points at `/Users/sarahtxy/dev/backstage_agent`, but operational reliability still depends on local machine setup, credentials, virtualenv state, and launchd installation.
- Dashboard review exists for decisions, reviewer impact, and on-demand role cover-letter drafts, but broader application draft management and correction feedback workflows are still limited.

## Known Issues

- Live Backstage submission is intentionally not implemented. When `DRY_RUN=false`, applications are blocked with `blocked_no_live_adapter`.
- Backstage authenticated page access depends on a local Playwright persistent browser profile and may fail on login expiration, Cloudflare challenges, CAPTCHA, or browser/session issues.
- Network and external service failures from IMAP, Backstage, OpenAI, or AI Builder are not fully surfaced with robust retry behavior.
- Duplicate prevention uses project and role keys plus title/date fallbacks; new Backstage formats may still produce duplicate or missed entries.
- The repository contains local SQLite backup files and generated package metadata. Do not treat those as source documentation.
- There are uncommitted source/test changes in the current worktree as of this documentation update; inspect `git status` before editing related files.

## Current Priorities

- Keep the default daily scan to a one-day window with macOS notification.
- Keep dry-run safety until the Backstage application flow is verified end to end.
- Continue adding parser and page-parser regression tests for every real-world parsing bug.
- Preserve the split between screening/review status and application blockers in storage, dashboard, and summaries.
- Keep project-level screening before role-level screening; role application drafting only runs for role decisions that remain `Auto Apply/Draft` after reviewer validation.
- Reuse captured actor profile/application facts instead of asking the user again for known facts.

## Important Constraints

- Source code is the source of truth when documentation is stale.
- Use `python3` on this machine unless the active virtualenv clearly provides another Python command.
- Runtime secrets belong in `.env` or environment variables, not in docs, logs, tests, or dashboard output.
- `profile.json` can contain real user profile data; avoid exposing it in documentation or test fixtures.
- Daily automation assumes macOS and uses `osascript` for notifications.
- Do not attempt to bypass Backstage login, Cloudflare, CAPTCHA, or other access controls.

## Recommended Next Steps

- Run the targeted test suite for parser, project page parser, project screener, storage dashboard, and CLI summary before changing scan semantics.
- Add run-log and error-reporting improvements for the launchd daily job.
- Add dashboard support for reviewing application drafts and recording corrections.
- Add exact-date rebuild/delete commands for safer reruns.
- Keep expanding tests around real Backstage email and page examples as they appear.
