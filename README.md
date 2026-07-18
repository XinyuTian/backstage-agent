# Backstage Automation Agent

A local-first, conservative automation agent for Backstage casting workflows. It scans recent Backstage notification emails, extracts casting projects and roles, screens them against an actor profile, stores decisions in SQLite, and prepares application drafts for promising matches.

The default workflow is intentionally safe:

- scan the latest day of Backstage notification emails
- run deterministic checks before spending LLM calls
- use a strict second-pass reviewer before applications
- store decisions and application blockers for auditability
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
python3 -m backstage_agent.cli show-config
python3 -m backstage_agent.cli ui
python3 -m backstage_agent.cli backstage-login
python3 -m backstage_agent.cli backstage-login-check
```

`parse-sample` is useful for parser tuning before connecting a real inbox.

The `ui` command starts a local dashboard at `http://127.0.0.1:8765` for searching and reviewing saved screening decisions.

## Workflow

1. `scan` fetches recent Backstage emails through IMAP.
2. The parser extracts project notices from each email.
3. The agent optionally fetches Backstage project pages and extracts role, location, and date details.
4. Project-level deterministic and LLM screening decide whether a project should proceed.
5. A stricter reviewer independently approves, rejects, or holds the project gate.
6. Approved projects proceed to role-level screening and review.
7. Approved roles are recorded as application drafts or blocked attempts.
8. The CLI prints a JSON summary and can send a macOS notification with `--notify`.

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

The script runs selection only (no candidate scoring). It invokes:

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

The repository contains the core local orchestration for email scanning, project and role parsing, two-layer screening, review, storage, dashboard review, dry-run application drafting, macOS notification, and daily scheduling assets.

Live Backstage submission is deliberately left as a guarded integration point. When `DRY_RUN=false`, application attempts are blocked until an account-specific browser flow is implemented and verified.
