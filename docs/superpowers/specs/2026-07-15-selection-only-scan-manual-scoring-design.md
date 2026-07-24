# Selection-Only Morning Scan and Manual Candidate Scoring

Date: 2026-07-15
Status: Approved design

## Problem

The scheduled morning command currently fetches recent Backstage email but combines two workflows in one `BackstageAgent.scan()` call:

1. the established project and role selection/review flow; and
2. the newer candidate feature extraction, scoring, ranking, and persistence flow.

The scan also stops processing a project as soon as `project_notice_exists()` finds a matching stored project. Recent daily logs show the consequence: an email is fetched and projects are parsed, but repeated projects produce no selection decisions because the entire project is skipped before its newest Backstage page is fetched.

Candidate scoring has a separate `rescore-candidates` command, but that command always clears existing scores for the date. There is no safe manual mode that preserves existing scores and processes only missing candidates.

## Goals

- Make the scheduled `scan` command run only the established selection, review, and application-draft workflow.
- Refresh repeated projects and roles from the newest digest and Backstage page data, then rerun selection instead of skipping them.
- Move candidate feature extraction, requirement matching, deterministic scoring, ranking, and persistence behind an explicit manual command.
- Preserve existing candidate scores by default.
- Allow the user to explicitly replace a date's existing candidate scores with `--overwrite`.
- Preserve the existing `rescore-candidates` command as a compatibility alias for overwrite mode.

## Non-Goals

- Changing selection policy, bucket semantics, reviewer behavior, application safety, or the one-day scheduled scan default.
- Automatically running candidate scoring after the morning scan.
- Changing scoring rules, score bands, feature extraction, calibration, or dashboard presentation.
- Performing live Backstage submission or bypassing Backstage access controls.

## CLI Design

The daily script continues to run:

```sh
.venv/bin/python -m backstage_agent.cli scan --days 1 --limit 25 --notify
```

`scan` no longer produces or persists candidate scores. Its JSON output may retain `candidates_scored` and `draft_suggestions` as zero-valued compatibility fields if removing them would unnecessarily break callers, but the summary must not imply scoring occurred.

The new manual command is:

```sh
.venv/bin/python -m backstage_agent.cli score-candidates --date 2026-07-15
```

By default, it generates candidates from stored projects and roles for the exact date, preserves candidate rows that already have scores, and scores only missing candidates.

Explicit replacement is:

```sh
.venv/bin/python -m backstage_agent.cli score-candidates --date 2026-07-15 --overwrite
```

Overwrite mode clears candidate rows for that date before rebuilding and reranking the complete date set.

The existing command remains available:

```sh
.venv/bin/python -m backstage_agent.cli rescore-candidates --date 2026-07-15
```

It delegates to the same scoring service with overwrite enabled. This preserves its current replacement semantics and avoids silently changing existing usage.

The manual command returns JSON containing at least:

- `date`
- `overwrite`
- `candidates_scored`
- `candidates_skipped_existing`
- `candidates_deleted`

## Morning Selection Data Flow

For each fetched digest, the scan parses every project in the requested time window. A matching stored project is no longer a reason to stop processing. Instead, storage resolves the stable project identity and refreshes mutable project fields from the newest digest and fetched project page.

The scan then refreshes or inserts the project's roles using stable role identities. The newest project and role objects are passed through the existing project screening, project review, role screening, role review, and guarded application-draft flow.

Latest decisions should be recorded through the existing auditable decision/review persistence model. Historical decision rows should not be broadly deleted merely to refresh a project. Dashboard queries should continue to resolve the latest applicable decision using their existing ordering semantics.

Candidate generation and scoring are absent from this path. The scan does not call the feature extractor, requirement matcher, scoring function, ranking function, or candidate persistence methods.

## Manual Scoring Data Flow

The manual scoring service loads stored project and role sources for the requested exact date and generates the same candidate identities used by the current scoring system.

In safe mode, it loads existing candidate identities for that date, excludes them from feature extraction and scoring, scores only missing identities, and then assigns ranks consistently across the combined existing and new date set. Existing scores and their audit payloads remain unchanged.

In overwrite mode, it first clears candidate rows for the requested date, then generates, scores, ranks, and persists the entire date set using the existing scoring implementation.

If no stored project sources exist for the date, the command succeeds with zero counts rather than fetching email implicitly. Email ingestion remains the responsibility of `scan`.

## Storage Behavior

The implementation should reuse existing project and role keys rather than adding parallel identity logic. Storage should expose narrowly scoped operations for:

- resolving and refreshing a matching project;
- refreshing or inserting roles for that project;
- finding existing candidate identities for a date; and
- clearing candidates for a date only when overwrite is explicitly selected.

Any migration required to track when a repeated project was most recently seen must be lightweight and backward compatible. The date used by manual scoring must represent the newest scan data included for that date, not only the project's original insertion date.

Candidate feedback and calibration records must not be deleted by safe mode. Overwrite mode may replace candidate rows as explicitly requested; any effect on feedback references must follow the database's existing foreign-key behavior and be covered by tests before implementation is accepted.

## Error Handling and Safety

- IMAP, Backstage page, model, and storage failures continue to surface through the current command failure path and daily error log.
- A page fetch failure should not discard usable newest digest data; selection can continue with the refreshed digest representation under existing fallback behavior.
- Safe scoring must never clear candidate rows.
- Destructive candidate clearing must be reachable only through `--overwrite` or the explicitly overwrite-oriented compatibility command.
- The daily launchd script must not pass either scoring command or an overwrite option.

## Testing

Tests will be written before implementation and will prove:

- a repeated stored project is refreshed and selected using newest data rather than skipped;
- refreshed roles use stable identities without uncontrolled duplication;
- `scan` does not invoke feature extraction or write candidate rows;
- the daily script invokes only selection scan behavior;
- `score-candidates --date` scores missing candidates and preserves existing score payloads;
- safe scoring reports skipped existing candidates and zero deletions;
- `score-candidates --date --overwrite` clears and rebuilds that date's candidates;
- `rescore-candidates` retains overwrite semantics through the shared implementation;
- candidate feedback handling in overwrite mode matches the documented storage behavior;
- CLI JSON reports the expected date, mode, and counts.

Targeted tests should cover agent orchestration, candidate storage, CLI candidate commands, and the daily script contract. Because the change crosses orchestration, storage, and CLI boundaries, the full test suite should run after targeted tests pass.

## Documentation

Implementation will update `PROJECT_STATE.md`, `CHANGELOG.md`, `README.md`, and `docs/module-guide.md` to describe selection-only scheduled scans and the explicit manual scoring commands. `ARCHITECTURE.md` should be updated only if the final implementation changes module boundaries or the documented system flow materially.

## Success Criteria

- A morning digest containing a previously stored project produces fresh selection decisions from the newest available data.
- The scheduled morning run produces no candidate scoring model calls or candidate score writes.
- Manual scoring is available through `score-candidates --date`.
- Existing scores are preserved unless the user passes `--overwrite` or invokes the compatibility `rescore-candidates` command.
- Command output makes preserved, created, and deleted work auditable.
