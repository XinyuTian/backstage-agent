# Backstage Automation Agent

An intelligent, cost-effective automation agent for scanning daily Backstage casting notification emails, screening roles for fit with an LLM, and preparing or submitting applications for matching roles.

The first version is intentionally conservative:

- Reads the latest day of Backstage notification emails through IMAP.
- Extracts candidate casting notices and application links.
- Uses deterministic rules before calling an LLM, keeping costs low.
- Stores every decision in SQLite for auditability.
- Defaults to dry-run mode so applications are drafted, not submitted.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
python -m backstage_agent.cli scan --limit 10 --days 1
```

## Configuration

Set environment variables directly or create a `.env` file:

```bash
IMAP_HOST=imap.gmail.com
IMAP_USERNAME=you@example.com
IMAP_PASSWORD=app-password
EMAIL_SUBJECT_KEYWORDS=basic filter
OPENAI_API_KEY=sk-...
ACTOR_PROFILE_PATH=profile.example.json
DRY_RUN=true
```

For Gmail, use an app password rather than your account password.

## Workflow

1. `scan` fetches recent Backstage emails whose subject includes the configured keywords.
2. The parser extracts casting notices from each email.
3. Cheap local filters reject obvious non-fits.
4. The LLM scores remaining roles against the actor profile.
5. Matching roles are written to the database and application drafts are created.
6. Live submission is blocked unless `DRY_RUN=false` and an application adapter is implemented.

Application questions that require personal knowledge, such as swimming ability, wardrobe ownership, exact availability, or comfort with specific scenes, should pause for user confirmation unless the answer is already captured in the actor profile.

## Commands

```bash
python -m backstage_agent.cli scan --limit 25 --days 1
python -m backstage_agent.cli parse-sample sample-email.html
python -m backstage_agent.cli decisions
python -m backstage_agent.cli show-config
python -m backstage_agent.cli ui
```

`parse-sample` is useful for tuning the parser before connecting a real inbox.

The `ui` command starts a local dashboard at `http://127.0.0.1:8765` for searching and reviewing saved screening decisions.

## Project Status

This repository contains the scaffold and core orchestration for the agent. The live Backstage submission adapter is deliberately left as a guarded integration point because it requires account-specific browser flow verification.
