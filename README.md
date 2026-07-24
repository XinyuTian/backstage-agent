# Backstage Automation Agent

A local-first, conservative automation agent for Backstage casting workflows. It scans recent Backstage notification emails, extracts casting projects and roles, scores mutual-selection candidates against an actor profile, stores decisions in SQLite, and prepares application drafts for promising matches.

The default workflow is scoring-first and intentionally safe:

- scan the latest day of Backstage notification emails
- refresh projects and roles, then score and rank candidates for that date
- always produce candidate scores and score traces instead of hiding opportunities behind a single filter
- preserve existing scores unless an overwrite is explicitly requested
- store scores, candidate feedback, and calibration proposals for auditability
- keep `DRY_RUN=true` unless live submission is deliberately implemented and verified

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python3 -m backstage_agent.cli scan --limit 10 --days 1
```

For development dependencies:

```bash
pip install -e '.[dev]'
```

## Configuration

Set environment variables directly or create a `.env` file:

```bash
IMAP_HOST=imap.gmail.com
IMAP_USERNAME=you@example.com
IMAP_PASSWORD=app-password
EMAIL_SUBJECT_KEYWORDS=basic filter
OPENAI_API_KEY=sk-...
AI_BUILDER_API_KEY=...
ACTOR_PROFILE_PATH=profile.example.json
DATABASE_PATH=backstage_agent.sqlite3
DRY_RUN=true
```

For Gmail, use an app password rather than your account password. Do not store a Backstage password in `.env`.

Useful settings:

- `LLM_PROVIDER`, `LLM_MODEL`, `MAX_LLM_CALLS_PER_SCAN`: first-pass screening provider, model, and budget.
- `REVIEWER_PROVIDER`, `REVIEWER_MODEL`, `MAX_REVIEWER_CALLS_PER_SCAN`: strict reviewer and cover-note provider, model, and budget.
- `MIN_MATCH_SCORE`: score threshold used by screeners and reviewers.
- `USE_BROWSER_FOR_BACKSTAGE`: enables authenticated Backstage page fetching through a persistent Playwright browser profile.
- `BACKSTAGE_BROWSER_PROFILE_PATH`: local browser profile path for stored Backstage session cookies.
- `BACKSTAGE_BROWSER_HEADLESS`: defaults to false because Backstage may challenge headless browser sessions.
- `BACKSTAGE_BROWSER_CHANNEL`: defaults to `chrome` when available.

## Commands

```bash
python3 -m backstage_agent.cli scan --limit 25 --days 1
python3 -m backstage_agent.cli scan --limit 25 --date 2026-07-09
python3 -m backstage_agent.cli parse-sample sample-email.html
python3 -m backstage_agent.cli decisions
python3 -m backstage_agent.cli candidates --limit 25
python3 -m backstage_agent.cli candidate-feedback 13 --human-score 45 --affected-components identity_match --failure-modes overweighted_signal --reason "Nationality over-weighted."
python3 -m backstage_agent.cli calibration-patterns
python3 -m backstage_agent.cli show-config
python3 -m backstage_agent.cli ui
python3 -m backstage_agent.cli backstage-login
python3 -m backstage_agent.cli backstage-login-check
```

`parse-sample` is useful for parser tuning before connecting a real inbox.

The daily `scan` command runs mutual-selection scoring automatically and preserves existing scores by default. The `score-candidates --date YYYY-MM-DD` command remains available for an explicit follow-up; add `--overwrite` only to intentionally delete and rebuild that date's scores. The `candidates` command lists ranked scores, `candidate-feedback` records a human correction, and `calibration-patterns` groups repeated taxonomy patterns into proposed scoring-rule changes.

The `ui` command starts a local dashboard at `http://127.0.0.1:8765` for searching and reviewing saved screening decisions. Candidate rankings are available at `http://127.0.0.1:8765/candidates`.

## Workflow

1. `scan` fetches recent Backstage emails through IMAP.
2. The parser extracts project notices from each email.
3. The agent optionally fetches Backstage project pages and extracts role, location, and date details.
4. Repeated projects and roles are refreshed in place from the newest digest/page data.
5. `scan` generates role or project-only candidates from the refreshed records.
6. It extracts structured features, matches requirements locally, calculates deterministic scores, and ranks the date's candidates.
7. Existing candidate identities are preserved and reported as skipped.
8. Human feedback can correct a candidate score and feed calibration proposals.
9. The CLI prints a scoring-oriented JSON summary and the daily scan can send a macOS notification with `--notify`.

The default scan does not run legacy project screening, role screening, reviewer calls, or application drafting. Historical decisions, dashboard views, storage interfaces, and compatibility code remain available pending the separately approved removal step.

Application questions that require personal knowledge, such as swimming ability, wardrobe ownership, exact availability, or comfort with specific scenes, should pause for user confirmation unless the answer is already captured in the actor profile.

## Persistent Backstage Login

For runs that need authenticated Backstage pages, use a dedicated local browser profile:

```bash
python3 -m backstage_agent.cli backstage-login
python3 -m backstage_agent.cli backstage-login-check
```

The first command opens a browser using `BACKSTAGE_BROWSER_PROFILE_PATH` so you can log in once. The second command checks whether that stored session is still logged in. Set `USE_BROWSER_FOR_BACKSTAGE=true` to let scans fetch Backstage pages through that authenticated profile.

If Backstage or Cloudflare blocks the automated browser, the agent should stop and report that status instead of trying to bypass the block.

## Daily Automation

The daily local run is defined in `scripts/daily_scan.sh` and scheduled by `launchd/com.sarahtxy.backstage-agent.daily.plist`. launchd runs the script at **9:00, 10:00, 11:00, and 12:00** local time.

The script runs the scoring-first daily workflow. It invokes:

```bash
python3 -m backstage_agent.cli scan --days 1 --limit 25
```

The scan command no longer passes `--notify`; the shell sends macOS notifications after inspecting the JSON result.

Retry behavior:

- If `messages_seen == 0` before noon, the job exits quietly and retries at the next hour.
- If the inbox is still empty at the noon attempt, the user is notified once (“No Backstage email today”) and later hours no-op for that date.
- After a successful scan for the day, later hourly runs skip quietly.

State is tracked in `logs/daily-scan-state.json`. Logs go to `logs/daily-scan.out.log` and `logs/daily-scan.err.log`.

After changing the launchd plist, reload the job:

```bash
launchctl bootout gui/$(id -u)/com.sarahtxy.backstage-agent.daily 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PWD/launchd/com.sarahtxy.backstage-agent.daily.plist"
```

The scheduled command refreshes and scores candidates automatically. It does not run the legacy screening, review, or application-drafting path.

Run candidate scoring manually for an exact date:

```bash
# Preserve existing scores and score only missing candidates.
.venv/bin/python -m backstage_agent.cli score-candidates --date 2026-07-15

# Delete and rebuild existing scores for that date.
.venv/bin/python -m backstage_agent.cli score-candidates --date 2026-07-15 --overwrite
```

The older `rescore-candidates --date YYYY-MM-DD` command remains an overwrite-mode compatibility alias.

To rerun the daily job from scratch and overwrite the active SQLite database, first move the current database into `backups/`. The next scan will recreate `backstage_agent.sqlite3` and ignore prior saved decisions:

```bash
cd /Users/sarahtxy/dev/backstage_agent
mkdir -p backups
ts=$(date '+%Y%m%d-%H%M%S')
mv backstage_agent.sqlite3 "backups/backstage_agent.sqlite3.${ts}.bak"
.venv/bin/python -m backstage_agent.cli scan --days 1 --limit 25 --notify
```

For an exact calendar date instead of the rolling one-day window, replace the last command with:

```bash
.venv/bin/python -m backstage_agent.cli scan --date "$(date '+%Y-%m-%d')" --limit 25 --notify
```

## Testing

Run the full test suite:

```bash
python3 -m pytest
```

For targeted work, run the relevant test file, for example:

```bash
python3 -m pytest tests/test_parser.py tests/test_project_page_parser.py
```

## Documentation For Future Agents

- `AGENTS.md`: required startup workflow and coding rules for future coding agents.
- `PROJECT_STATE.md`: current capabilities, priorities, constraints, and known issues.
- `CHANGELOG.md`: concise behavior-focused change history.
- `ARCHITECTURE.md`: system flow, module responsibilities, storage, and integrations.
- `docs/module-guide.md`: task-oriented map from likely changes to relevant files and tests.

## Project Status

The repository contains the core local orchestration for email scanning, project and role parsing, candidate-first mutual-selection scoring, two-layer screening, review, storage, dashboard review, dry-run application drafting, macOS notification, and daily scheduling assets.

Live Backstage submission is deliberately left as a guarded integration point. When `DRY_RUN=false`, application attempts are blocked until an account-specific browser flow is implemented and verified.
