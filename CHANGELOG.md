# Changelog

Future changes in this file should be concise and behavior-focused. Include user-visible behavior, important internal behavior, interfaces, configuration, storage schema, automation, and architecture changes. Do not use this as a task diary, and do not list every file edited.

## Unreleased

### Added

- Introduced lightweight repository documentation for future coding agents, including project state, architecture, module guide, and agent workflow instructions.
- Added a role-selection decision core with five final buckets, structured first-pass LLM output validation, downgrade-only reviewer validation, reusable `screening_rules.json`, and tests.
- Persisted structured classifier/reviewer artifacts, final bucket, reviewer impact, and schema errors on decision rows.
- Added candidate scoring persistence for ranked candidates, human feedback taxonomy capture, calibration proposal storage, and `DecisionStore` interfaces for candidate search and feedback pattern aggregation.
- Added candidate-first mutual-selection scoring with LLM feature extraction, local requirement matching, deterministic score traces, ranked bands, draft suggestions, human feedback, dashboard candidate review, and calibration proposals.
- Added an on-demand dashboard cover-letter button at the bottom of role detail panels, using the existing profile-grounded draft generation prompt and displaying the latest generated draft.
- Added `score-candidates --date YYYY-MM-DD [--overwrite]` for safe manual scoring, with preservation of existing scores by default and explicit date replacement when requested.

### Changed

- Daily automation retries the selection scan at 9:00, 10:00, 11:00, and 12:00 when no Backstage email is seen yet; the shell notifies on success or after the final noon miss, tracks per-day state in `logs/daily-scan-state.json`, and no longer passes `--notify` to the scan CLI.
- Refreshed README structure so setup, configuration, commands, daily automation, testing, and project status are easier to scan.
- Recorded active Instagram tagging as an allowed actor preference and instructed project/role screeners not to reject roles for that requirement.
- Updated scan orchestration so projects are screened and reviewed before roles, role reviews receive the first model bucket/artifacts, and application drafting only runs for roles that remain `Auto Apply/Draft` after reviewer validation.
- Changed scan orchestration so project evaluation contributes to candidate scoring instead of acting as a hard project-level filter for the new scoring path.
- Updated CLI summaries and dashboard labels/counts to expose final buckets and reviewer impact while preserving legacy decision fields.
- Separated daily selection from candidate scoring: `scan` now refreshes repeated projects and roles from newest data and runs only screening, review, and application drafting; `rescore-candidates` remains an overwrite-mode compatibility alias.

### Fixed

- Fixed role gender local screening so explicit role gender requirements take precedence over softer title/pronoun heuristics, preventing titles like `Run for Your Wife - John Smith` from falling through to role LLM screening.
- Fixed candidate scoring follow-through so project gate/reviewer outcomes influence deterministic score caps, candidate ranks are global across the scan, dashboard feedback records durable corrections, feature extraction obeys the scan LLM budget, and packaged CLI runs can load scoring rules outside the repository directory.
- Fixed candidate rescoring for real model outputs by normalizing loose feature containers, retrying malformed feature JSON once, tolerating string-valued requirements, and adding an exact-date `rescore-candidates` command for stored projects and roles.

### Removed

- Nothing yet.

## Recent History From Git

- `cc93489` added two-layer filtering, matching the current project-gate and role-level screening flow.
- `96758e6` added tests and cover-letter behavior.
- `63e31aa` added packaging files.
