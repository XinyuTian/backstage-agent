# Architecture

## System Overview

Backstage Agent is a CLI-first Python package under `src/backstage_agent`. Its daily path fetches Backstage casting notification emails, refreshes project and role data, and scores mutual-selection candidates against local actor facts and project signals. The same scoring service remains available through a manual exact-date command.

The system is intentionally conservative: the default is dry-run application drafting, not live submission.

## Main Workflow

1. `src/backstage_agent/cli.py` handles `scan` arguments and loads settings.
2. `BackstageAgent.scan()` in `src/backstage_agent/agent.py` fetches recent email messages from IMAP.
3. `parser.parse_project_notices()` extracts project-level notices from each email digest.
4. `DecisionStore` refreshes matching project and role identities with the newest digest/page data.
5. `ProjectPageClient` fetches project-page HTML through normal HTTP or an authenticated Playwright browser profile when enabled.
6. `project_page_parser` extracts page context, shooting info, and role-level notices when page HTML is available.
7. `candidate_generation` creates role candidates or a project-only candidate when explicit roles are missing.
8. `FeatureExtractor` extracts structured facts, `requirement_matcher` checks local actor facts, and `scoring` calculates deterministic scores and ranks.
9. `DecisionStore` preserves existing candidate identities by default and persists new score artifacts.
10. The CLI prints a scoring-oriented JSON summary and optionally sends a macOS notification.

The default scan does not invoke legacy project screening, role screening, reviewer calls, or application drafting. Those modules, historical tables, storage interfaces, and dashboard views remain compatibility code pending a separately approved removal step.

Manual `score-candidates --date YYYY-MM-DD` runs the same stored-date scoring service. Existing scores are preserved unless `--overwrite` is supplied.

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
- `candidate_models.py`: candidate, feature, requirement match, score, feedback, and calibration data structures.
- `candidate_generation.py`: role and project-only candidate generation from parsed projects and roles.
- `feature_extractor.py`: structured LLM feature extraction that does not produce scores or decisions.
- `requirement_matcher.py`: local requirement matching against stored actor facts.
- `scoring.py`: deterministic score, cap, band, trace, draft-suggestion, and ranking logic.
- `calibration.py`: proposal generation from repeated human feedback taxonomy patterns.
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

Daily scoring: email message -> refreshed project/role records -> candidate generation -> LLM feature extraction -> local requirement matching -> deterministic scoring/ranking -> SQLite candidate rows -> human feedback -> calibration proposals.

Manual scoring enters the same flow at stored project/role records.

Project-level decisions are stored in the same `decisions` table as role-level decisions, using the sentinel role value from `PROJECT_GATE_ROLE`.

## Candidate Scoring

- `candidate_models.py` defines candidate, feature, requirement match, score, feedback, and calibration data structures.
- `candidate_generation.py` creates role and project-only candidates from parsed projects and roles.
- `feature_extractor.py` asks the LLM for structured features only.
- `requirement_matcher.py` checks extracted requirements against local actor facts.
- `scoring.py` computes deterministic scores, bands, caps, and ranks.
- `calibration.py` turns repeated human feedback patterns into scoring-rule proposals.

## State and Storage

SQLite is the main durable state store. By default it is `backstage_agent.sqlite3`, controlled by `DATABASE_PATH`.

Main tables:

- `projects`: parsed project notices, project keys, page-derived shooting info.
- `roles`: role notices associated with projects.
- `candidates`: role and project-only candidate scores, feature payloads, requirement-match payloads, ranked bands, and draft suggestions.
- `candidate_feedback`: human score corrections, score deltas, affected components, failure modes, and free-text reasons.
- `calibration_proposals`: proposed scoring-rule adjustments produced from repeated feedback patterns.
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
