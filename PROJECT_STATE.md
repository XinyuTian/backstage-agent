# Project State

Last updated: 2026-07-24

This file represents the present state of the project. Edit it in place as functionality, priorities, blockers, or known issues change; do not use it as a historical log.

## Current Objective

Build a conservative local automation agent that scans daily Backstage casting emails, refreshes projects and roles, scores candidates against the actor profile, and stores auditable rankings.

## Current Capabilities

- CLI package `backstage-agent` / `python3 -m backstage_agent.cli` with commands for scoring-first daily scanning, safe/overwrite follow-up candidate scoring, sample parsing, ranked candidates, candidate feedback, calibration proposals, config display, dashboard serving, and persistent Backstage login checks.
- IMAP email ingestion in `src/backstage_agent/email_client.py`, defaulting to recent Backstage-related messages and supporting `--days` or an exact `--date`.
- Email digest parsing in `src/backstage_agent/parser.py` and optional Backstage project-page parsing in `src/backstage_agent/project_page_parser.py`.
- Legacy screening, review, application-drafting, decision CLI, and decision-dashboard runtime code has been removed.
- SQLite persistence in `src/backstage_agent/storage.py` for projects, roles, candidates, feedback, calibration proposals, keys, shooting locations, and shooting dates.
- Daily mutual-selection scoring that generates role and project-only candidates, extracts LLM features, matches local requirements, computes deterministic scores, stores ranked bands, and records draft suggestions.
- Daily scoring refreshes repeated project and role identities from the newest digest and Backstage page data, then preserves existing candidate scores by default.
- Candidate-first storage in `src/backstage_agent/storage.py` for ranked candidates, structured feature and requirement-match payloads, human score feedback, feedback-pattern aggregation, and calibration proposals.
- Human feedback capture for candidate score disagreement and calibration proposal generation, using reusable taxonomy fields instead of one-off prompt tweaks.
- Candidate-only dashboard in `src/backstage_agent/ui.py` at `http://127.0.0.1:8765/candidates` for ranked candidates and score feedback.
- macOS notification helper in `src/backstage_agent/notifier.py` and daily launchd assets in `scripts/daily_scan.sh` and `launchd/com.sarahtxy.backstage-agent.daily.plist`.

## In Progress

- Parser and project-page extraction are being actively hardened against real Backstage digest/page variations.
- The daily scan path is present and points at `/Users/sarahtxy/dev/backstage_agent`, with launchd retries at 9:00–12:00 when no Backstage email has arrived yet; operational reliability still depends on local machine setup, credentials, virtualenv state, and launchd installation.
- Dashboard review exists for ranked candidates and candidate feedback; accepting/rejecting calibration proposals remains CLI/storage-only.
- Candidate persistence, CLI feedback capture, and calibration proposal storage now exist, but accepting/rejecting calibration proposals and automatically rewriting `scoring_rules.json` remain manual.



## Known Issues

- Existing SQLite databases may retain inert legacy `decisions` and `applications` rows; the application no longer reads or writes them.
- Backstage authenticated page access depends on a local Playwright persistent browser profile and may fail on login expiration, Cloudflare challenges, CAPTCHA, or browser/session issues.
- Network and external service failures from IMAP, Backstage, OpenAI, or AI Builder are not fully surfaced with robust retry behavior.
- Duplicate prevention uses project and role keys plus title/date fallbacks; new Backstage formats may still produce duplicate or missed entries.
- The repository contains local SQLite backup files and generated package metadata. Do not treat those as source documentation.

## Current Priorities

- Keep the default daily scan to a one-day window with macOS notification; retry hourly at 9–12 when `messages_seen == 0`.
- Continue adding parser and page-parser regression tests for every real-world parsing bug.
- Keep candidate scoring in the default daily scan and preserve existing scores unless overwrite is explicitly requested.
- Keep candidate feedback taxonomy and calibration records auditable so repeated scoring mistakes can be aggregated across all tagged components and failure modes.
- Reuse captured actor profile/application facts instead of asking the user again for known facts.

## Important Constraints

- Source code is the source of truth when documentation is stale.
- Use `python3` on this machine unless the active virtualenv clearly provides another Python command.
- Runtime secrets belong in `.env` or environment variables, not in docs, logs, tests, or dashboard output.
- `profile.json` can contain real user profile data; avoid exposing it in documentation or test fixtures.
- Daily automation assumes macOS and uses `osascript` for notifications.
- Do not attempt to bypass Backstage login, Cloudflare, CAPTCHA, or other access controls.

## Recommended Next Steps

- Validate the first scheduled scoring-first run through its logs, macOS notification, and candidate dashboard results.
- Add run-log and error-reporting improvements for the launchd daily job.
- Add dashboard support for reviewing and accepting calibration proposals.
- Add exact-date rebuild/delete commands for safer reruns.
- Keep expanding tests around real Backstage email and page examples as they appear.
