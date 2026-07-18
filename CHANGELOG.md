# Changelog

Future changes in this file should be concise and behavior-focused. Include user-visible behavior, important internal behavior, interfaces, configuration, storage schema, automation, and architecture changes. Do not use this as a task diary, and do not list every file edited.

## Unreleased

### Added

- Introduced lightweight repository documentation for future coding agents, including project state, architecture, module guide, and agent workflow instructions.
- Added a role-selection decision core with five final buckets, structured first-pass LLM output validation, downgrade-only reviewer validation, reusable `screening_rules.json`, and tests.
- Persisted structured classifier/reviewer artifacts, final bucket, reviewer impact, and schema errors on decision rows.
- Added an on-demand dashboard cover-letter button at the bottom of role detail panels, using the existing profile-grounded draft generation prompt and displaying the latest generated draft.

### Changed

- Daily automation retries the selection scan at 9:00, 10:00, 11:00, and 12:00 when no Backstage email is seen yet; the shell notifies on success or after the final noon miss, tracks per-day state in `logs/daily-scan-state.json`, and no longer passes `--notify` to the scan CLI.
- Refreshed README structure so setup, configuration, commands, daily automation, testing, and project status are easier to scan.
- Recorded active Instagram tagging as an allowed actor preference and instructed project/role screeners not to reject roles for that requirement.
- Updated scan orchestration so projects are screened and reviewed before roles, role reviews receive the first model bucket/artifacts, and application drafting only runs for roles that remain `Auto Apply/Draft` after reviewer validation.
- Updated CLI summaries and dashboard labels/counts to expose final buckets and reviewer impact while preserving legacy decision fields.

### Fixed

- Fixed role gender local screening so explicit role gender requirements take precedence over softer title/pronoun heuristics, preventing titles like `Run for Your Wife - John Smith` from falling through to role LLM screening.

### Removed

- Nothing yet.

## Recent History From Git

- `cc93489` added two-layer filtering, matching the current project-gate and role-level screening flow.
- `96758e6` added tests and cover-letter behavior.
- `63e31aa` added packaging files.
