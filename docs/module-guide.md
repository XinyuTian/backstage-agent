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

## Candidate Scoring

- Start with `src/backstage_agent/agent.py` for the scoring-first daily `scan` orchestration and the shared exact-date scoring service.
- Start with `src/backstage_agent/cli.py` for `score-candidates --date YYYY-MM-DD [--overwrite]` and the overwrite-mode `rescore-candidates` compatibility alias.
- Use `src/backstage_agent/candidate_models.py` for candidate, feature, requirement match, score, feedback, and calibration data structures.
- Use `src/backstage_agent/candidate_generation.py` for role and project-only candidates from parsed projects and roles.
- Use `src/backstage_agent/feature_extractor.py` for structured LLM feature extraction that returns facts only, not scores.
- Use `src/backstage_agent/requirement_matcher.py` for local requirement matching against stored actor facts.
- Use `src/backstage_agent/scoring.py` for deterministic scores, bands, caps, traces, draft suggestions, and ranking.
- Use `src/backstage_agent/calibration.py` for turning repeated feedback patterns into scoring-rule proposals.
- Relevant tests: `tests/test_candidate_models.py`, `tests/test_candidate_generation.py`, `tests/test_feature_extractor.py`, `tests/test_requirement_matcher.py`, `tests/test_candidate_scoring.py`, `tests/test_agent_candidate_scoring.py`, `tests/test_candidate_storage.py`, `tests/test_cli_candidates.py`, `tests/test_ui_candidates.py`, and `tests/test_calibration.py`.

## Storage And Dashboard

- Start with `src/backstage_agent/storage.py` for SQLite schema, persistence, search filters, status counts, and lightweight migrations.
- Use `src/backstage_agent/ui.py` for dashboard rendering, filters, status labels, candidate rankings, candidate feedback form affordances, and application blocker display.
- Existing legacy decision/application rows are inert and have no runtime readers or writers.
- Candidate rows include score JSON, feature JSON, requirement-match JSON, ranked band, rank position, and draft-suggestion fields.
- Relevant tests: `tests/test_storage_dashboard.py`, `tests/test_candidate_storage.py`, `tests/test_ui_labels.py`, `tests/test_ui_candidates.py`.

## Backstage Browser Access

- Start with `src/backstage_agent/browser_session.py` for Playwright persistent profile behavior, login checks, and authenticated HTML fetches.
- Use `src/backstage_agent/web_client.py` for the choice between direct HTTP and browser-backed fetching.
- Do not bypass login gates, Cloudflare challenges, CAPTCHA, or other access controls.

## Identifiers And De-Duplication

- Start with `src/backstage_agent/identifiers.py` for project and role key derivation.
- Storage duplicate checks live in `src/backstage_agent/storage.py`.
- Parser changes that affect titles, URLs, project dates, roles, or descriptions may affect de-duplication.
