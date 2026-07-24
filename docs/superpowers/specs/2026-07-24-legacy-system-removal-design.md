# Legacy System Removal Design

Date: 2026-07-24

## Goal

Remove the old screening, review, decision, application-drafting, and
decision-dashboard system from the active product while preserving existing
SQLite records as inert historical data.

## Scope

The scoring-first daily workflow remains the only active selection system:

1. Fetch recent Backstage email.
2. Parse and refresh projects and roles.
3. Generate role or project-only candidates.
4. Extract features, match requirements, score, rank, and persist candidates.
5. Collect candidate feedback and calibration proposals.

The removal must not change one-day scheduling, empty-inbox retries, macOS
notification behavior, dashboard recovery, Backstage page fetching, scoring
fallbacks, score preservation, or explicit overwrite semantics.

## Code Removal

Delete the legacy modules and their dedicated tests:

- `src/backstage_agent/project_screener.py`
- `src/backstage_agent/screener.py`
- `src/backstage_agent/reviewer.py`
- `src/backstage_agent/decision_core.py`
- `src/backstage_agent/application.py`
- structured screening, reviewer, decision-core, application, and legacy
  screening-policy tests

Remove legacy imports, constructor wiring, helper functions, and result fields
from `BackstageAgent`. `ScanResult` will contain only ingestion and scoring
counters needed by the CLI and daily script.

Delete legacy decision/review/application model types only after confirming no
candidate-scoring or ingestion interface consumes them. Shared project, role,
email, profile, and parsing models remain.

## CLI Removal

Remove:

- the `decisions` command;
- legacy decision, review, and application counts from scan JSON;
- bucket and screening-budget summary helpers;
- imports used only by legacy decision output.

Keep:

- `scan`;
- `candidates`;
- candidate feedback and calibration commands;
- manual safe/overwrite scoring commands;
- parsing, configuration, database-administration, dashboard, and Backstage
  login commands.

## Dashboard Removal

The candidate dashboard becomes the sole dashboard:

- `/` redirects to `/candidates`;
- `/candidates` continues to render ranked candidates;
- `/candidate-feedback` continues to record feedback;
- legacy decision search, filters, counts, detail panels, application links,
  and cover-letter actions are removed;
- `/cover-letter` is removed.

Candidate dashboard styles and helpers will be retained and simplified only as
needed. The daily dashboard health check continues to validate the same local
server.

## Storage and Historical Data

Remove runtime storage methods that create, update, search, count, or join
legacy decisions, reviews, and applications.

Existing SQLite records must not be deleted, rewritten, migrated, or compacted.
The removal will not execute `DROP TABLE`, `DELETE`, destructive migrations, or
active-database cleanup.

To keep opening existing databases safe, legacy tables may remain in the
schema-creation compatibility block if removing their creation would require a
destructive or versioned schema migration. They will have no runtime readers or
writers. A later explicit archival or schema migration can remove them if the
user requests it.

Candidate storage, candidate feedback, calibration proposals, projects, roles,
and their ingestion/rescoring queries remain active.

## Configuration

Remove settings and environment documentation only when they are exclusively
used by the deleted screeners, reviewer, or application service. Keep all model
provider settings required by candidate feature extraction or cover-letter-free
scoring, and keep `DRY_RUN` if database or CLI compatibility still exposes it.

No secrets or active local configuration files will be rewritten.

## Documentation

Update `README.md`, `PROJECT_STATE.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, and
`docs/module-guide.md` to describe a scoring-only product. Do not describe the
legacy system as available or viewable. State that old SQLite rows may remain
in existing databases but are no longer accessed by the application.

## Testing

Test-first removal will verify:

- `BackstageAgent` has no legacy service dependencies;
- scan results and CLI JSON contain only scoring-era fields;
- the `decisions` command is unavailable;
- `/` redirects to `/candidates`;
- candidate list and feedback routes remain functional;
- `/cover-letter` is unavailable;
- candidate storage and scoring still work against a database containing
  legacy tables and rows;
- daily scheduling, retry, notification, and dashboard-health behavior remain
  unchanged;
- deleted legacy modules have no remaining imports or documentation references.

The targeted agent, CLI, UI, storage, and daily-script tests will run first.
The full remaining test suite must pass before merge.

## Rollout and Safety

Implementation will occur on a feature branch created from current `main`.
After review and verification, it will be merged locally into `main`.

The task will not:

- delete database records or backup files;
- run a live inbox scan;
- access authenticated Backstage pages;
- call external model providers;
- deliver a real macOS notification;
- reload or trigger launchd;
- push changes to a remote repository.

The existing scheduled job will pick up the scoring-only code from the local
checkout on its next normal run.
