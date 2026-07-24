# Architecture

## System Overview

Backstage Agent is a CLI-first Python package under `src/backstage_agent`. Its daily path fetches Backstage casting notification emails, refreshes project and role data, and scores mutual-selection candidates against local actor facts and project signals. The same scoring service remains available through a manual exact-date command.

The system is scoring-only and does not draft or submit applications.

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

Legacy screening, review, application drafting, decision CLI, and decision dashboard modules have been removed.

Manual `score-candidates --date YYYY-MM-DD` runs the same stored-date scoring service. Existing scores are preserved unless `--overwrite` is supplied.

## Module Responsibilities

- `cli.py`: command-line entry point and scan summary formatting.
- `settings.py`: `.env` loading, environment parsing, and actor profile loading.
- `models.py`: actor profile, email, project, and role dataclasses.
- `agent.py`: high-level scan orchestration.
- `email_client.py`: IMAP search, fetch, date-window filtering, MIME decoding.
- `parser.py`: email digest and fallback casting notice parsing.
- `project_page_parser.py`: Backstage project-page role, shooting location, and shooting date extraction.
- `web_client.py`: unauthenticated HTTP project-page fetches and browser-backed authenticated fetch dispatch.
- `browser_session.py`: Playwright persistent profile login, login checks, and authenticated HTML fetches.
- `project_context.py`: project description enrichment from page and role data.
- `candidate_models.py`: candidate, feature, requirement match, score, feedback, and calibration data structures.
- `candidate_generation.py`: role and project-only candidate generation from parsed projects and roles.
- `feature_extractor.py`: structured LLM feature extraction that does not produce scores or decisions.
- `requirement_matcher.py`: local requirement matching against stored actor facts.
- `scoring.py`: deterministic score, cap, band, trace, draft-suggestion, and ranking logic.
- `calibration.py`: proposal generation from repeated human feedback taxonomy patterns.
- `storage.py`: SQLite schema compatibility, project/role/candidate persistence, feedback, and calibration queries.
- `ui.py`: candidate-only local HTTP dashboard and feedback form.
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
Existing databases may retain inert `decisions` and `applications` tables. They are not read or written by runtime code and are retained only to avoid destructive data loss.

Schema creation and lightweight migrations happen in `DecisionStore._ensure_schema()`. There is no separate migration framework.

Local files that may contain sensitive or machine-specific state include `.env`, `profile.json`, `backstage_agent.sqlite3`, `browser_profiles/`, and `logs/`.

## External Services and Integrations

- IMAP mailbox access, typically Gmail with an app password.
- OpenAI-compatible chat completion APIs for candidate feature extraction.
- Backstage public or authenticated project pages.
- Playwright Chromium/Chrome persistent profile for logged-in Backstage page fetches.
- macOS `osascript` for desktop notifications.
- `launchd` for the daily local schedule.

## Configuration

Configuration is loaded in `settings.py` from environment variables after `python-dotenv` reads `.env`.

Important variables include:

- IMAP: `IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `EMAIL_SEARCH_QUERY`, `EMAIL_SUBJECT_KEYWORDS`.
- Feature extraction: `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY`, `AI_BUILDER_API_KEY`, `AI_BUILDER_BASE_URL`, `MAX_LLM_CALLS_PER_SCAN`.
- Local state: `ACTOR_PROFILE_PATH`, `DATABASE_PATH`.
- Browser-backed Backstage access: `BACKSTAGE_BROWSER_PROFILE_PATH`, `USE_BROWSER_FOR_BACKSTAGE`, `BACKSTAGE_BROWSER_HEADLESS`, `BACKSTAGE_BROWSER_CHANNEL`.

## Architectural Constraints

- Keep the daily automation optimized for one-day scans and macOS notification.
- Do not store Backstage passwords; use the persistent browser profile for session cookies.
- Avoid broad schema churn unless it is clearly needed; storage currently relies on inline schema creation and migration.
- Prefer tests around parsers, scoring, storage queries, candidate UI, and CLI summaries when behavior changes.
