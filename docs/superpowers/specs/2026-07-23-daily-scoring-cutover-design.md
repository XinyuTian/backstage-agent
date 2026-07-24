# Daily Scoring Cutover Design

Date: 2026-07-23

## Goal

Make candidate scoring the daily and default Backstage workflow while preserving
the legacy screening system, historical decisions, storage compatibility, and
dashboard access. Removing the legacy system is explicitly deferred to a second
project after the scoring workflow has operated successfully.

## Current State

The `scan` command fetches recent Backstage email, refreshes project and role
records, then runs the legacy project screening, reviewer, role screening,
reviewer, and application-drafting flow. Candidate scoring is available only as
the separate `score-candidates --date YYYY-MM-DD [--overwrite]` command.

The launchd-managed daily script calls `scan --days 1 --limit 25`, so the
scheduled workflow currently runs legacy selection and does not score
candidates.

## Chosen Design

`scan` will become one scoring-first pipeline:

1. Fetch the requested email window or exact date.
2. Parse projects and fetch the latest available project-page context.
3. Upsert projects and roles so repeated listings use the newest data.
4. Generate candidates from the projects and roles seen for the scan date.
5. Extract candidate features, match local requirements, calculate deterministic
   scores, rank all candidates for the date, and persist the results.
6. Return a scan summary centered on refreshed projects, roles, candidates
   scored, existing candidates skipped, and scoring fallbacks.

The scan will not invoke legacy project screening, project review, role
screening, role review, or application drafting.

Candidate scoring will remain idempotent by default. Existing candidate
identities for the date will be preserved and reported as skipped. The existing
explicit overwrite command will remain available for intentional rebuilding.

## Compatibility Boundary

This cutover does not delete or rewrite:

- legacy screening, reviewer, or application code;
- legacy decision, review, or application tables;
- historical screening or application records;
- legacy dashboard views;
- legacy storage interfaces;
- the manual `score-candidates` and `rescore-candidates` commands.

Compatibility code may remain callable directly for historical inspection or
the later removal project, but it will no longer be part of default or scheduled
execution.

## Daily Automation

The existing launchd schedule and retry window remain unchanged. The daily
script will continue invoking `scan --days 1 --limit 25`; because `scan` becomes
the scoring pipeline, no second command or launchd reconfiguration is required.

The successful macOS notification and log summary will describe the scoring
result. Empty-inbox retry behavior and the closing dashboard health check remain
unchanged.

## Error Handling

Existing candidate-scoring fallback behavior remains in effect: feature
extraction, requirement matching, scoring, or ranking failures produce
conservative auditable fallback artifacts rather than silently dropping a
candidate.

Email, parsing, page-fetch, or persistence failures retain the current command
failure behavior. An empty inbox remains a valid zero-message result so the
daily retry script can retry until noon.

## Testing

Tests will verify:

- `scan` refreshes projects and roles and scores candidates;
- `scan` does not call legacy screeners, reviewers, or application drafting;
- repeated daily execution preserves existing scores by default;
- exact-date and one-day scan behavior remain supported;
- CLI JSON and human summaries report scoring-oriented counts;
- the daily script retains retry, notification, and dashboard recovery behavior;
- historical decision and dashboard compatibility remains intact.

Targeted orchestration, candidate, CLI, and daily-script tests will run first.
Because the cutover crosses orchestration, CLI, automation, storage, and UI
compatibility boundaries, the full test suite must pass before merging to
`main`.

## Rollout

The candidate-scoring branch will first receive the cutover implementation and
documentation. After verification, it will be merged locally into `main`, and
the merged result will be tested again.

Live IMAP, Backstage browser access, external model calls, macOS notification
delivery, and launchd execution will not be triggered as part of automated
verification unless separately authorized. The first scheduled production run
therefore remains the operational validation point.

## Deferred Work

Deleting the legacy screening system is step 2 and is outside this design. That
work will separately identify removable modules, commands, dashboard views,
storage interfaces, tests, documentation, and any historical-data migration or
archival requirements.
