# Changelog

Future changes in this file should be concise and behavior-focused. Include user-visible behavior, important internal behavior, interfaces, configuration, storage schema, automation, and architecture changes. Do not use this as a task diary, and do not list every file edited.

## Unreleased

### Added

- Added append-only normalized calibration evidence, latest-label supersession per stable candidate/component, legacy feedback backfill, versioned residual evaluation, auditable historical weight decay, and idempotent bootstrap proposals capped at plus or minus five points.
- Added resolved scoring snapshots and a single production/display recomputation path for component totals, caps, and bands.
- Added stable per-candidate/component corrections with optional reasons, overwrite-in-place semantics, Reset, stale-version Reconfirm, and current-correction calibration patterns.
- Introduced lightweight repository documentation for future coding agents, including project state, architecture, module guide, and agent workflow instructions.
- Added a role-selection decision core with five final buckets, structured first-pass LLM output validation, downgrade-only reviewer validation, reusable `screening_rules.json`, and tests.
- Persisted structured classifier/reviewer artifacts, final bucket, reviewer impact, and schema errors on decision rows.
- Added candidate scoring persistence for ranked candidates, human feedback taxonomy capture, calibration proposal storage, and `DecisionStore` interfaces for candidate search and feedback pattern aggregation.
- Added candidate-first mutual-selection scoring with LLM feature extraction, local requirement matching, deterministic score traces, ranked bands, draft suggestions, human feedback, dashboard candidate review, and calibration proposals.
- Added an on-demand dashboard cover-letter button at the bottom of role detail panels, using the existing profile-grounded draft generation prompt and displaying the latest generated draft.
- Added `score-candidates --date YYYY-MM-DD [--overwrite]` for safe manual scoring, with preservation of existing scores by default and explicit date replacement when requested.

### Changed

- Added the candidate grid's uncapped component sum as the first `Pre-cap total` column so score-cap effects are visible during review.
- Replaced nested candidate evidence payloads with an adaptive single-column detail view that omits empty sections, flattens requirements, and keeps original listing text collapsed.
- Made the candidate workbench's 22/78 desktop split adjustable by pointer drag or keyboard (16-pixel arrow steps, Home, and End), while keeping the divider hidden on mobile and restoring the default split on reload.
- Made Backstage digest subject dates take precedence over message receipt dates, and use the resulting project date for candidate workbench ordering and exact-day/seven-day filtering.
- Compacted the candidate workbench with a green header, date navigation, simplified evidence, and a bottom spreadsheet-style component grid containing only agent-score and correction rows; correction links and saves preserve the selected date window.
- Replaced the candidate card wall with an English left-list/right-detail score-review workbench that overlays corrections without mutating official candidate rows.
- Added the mutual-selection scoring-system diagram to `README.md`.
- Made `scan` the scoring-first daily workflow: it refreshes projects and roles, scores and ranks candidates for the scan date, preserves existing scores by default, and no longer invokes legacy screening, review, or application drafting. Legacy data, dashboard views, and compatibility code remain available.
- Daily automation retries the selection scan at 9:00, 10:00, 11:00, and 12:00 when no Backstage email is seen yet; the shell notifies on success or after the final noon miss, tracks per-day state in `logs/daily-scan-state.json`, and no longer passes `--notify` to the scan CLI.
- Refreshed README structure so setup, configuration, commands, daily automation, testing, and project status are easier to scan.
- Recorded active Instagram tagging as an allowed actor preference and instructed project/role screeners not to reject roles for that requirement.
- Updated scan orchestration so projects are screened and reviewed before roles, role reviews receive the first model bucket/artifacts, and application drafting only runs for roles that remain `Auto Apply/Draft` after reviewer validation.
- Changed scan orchestration so project evaluation contributes to candidate scoring instead of acting as a hard project-level filter for the new scoring path.
- Updated CLI summaries and dashboard labels/counts to expose final buckets and reviewer impact while preserving legacy decision fields.
- Separated daily selection from candidate scoring: `scan` now refreshes repeated projects and roles from newest data and runs only screening, review, and application drafting; `rescore-candidates` remains an overwrite-mode compatibility alias.

### Fixed

- Fixed incompatible casting-gender requirements so canonical and numbered extraction shapes use stored profile genders and receive the existing mandatory-mismatch cap instead of unknown-requirement partial credit.
- Prevented empty extracted requirements from being treated as mandatory mismatches or triggering candidate score caps.
- Styled all candidate date-navigation controls like the filled green Filter button and replaced icon arrows with compact `<` and `>` labels.
- Fixed candidate-workbench correction typing so enabling feedback no longer steals focus from multi-digit numeric entry, and made the visible `7 days` control toggle back to exact-day mode with an accessible active state.
- Fixed role gender local screening so explicit role gender requirements take precedence over softer title/pronoun heuristics, preventing titles like `Run for Your Wife - John Smith` from falling through to role LLM screening.
- Fixed candidate scoring follow-through so project gate/reviewer outcomes influence deterministic score caps, candidate ranks are global across the scan, dashboard feedback records durable corrections, feature extraction obeys the scan LLM budget, and packaged CLI runs can load scoring rules outside the repository directory.
- Fixed candidate rescoring for real model outputs by normalizing loose feature containers, retrying malformed feature JSON once, tolerating string-valued requirements, and adding an exact-date `rescore-candidates` command for stored projects and roles.

### Removed

- Removed the legacy project/role screening, reviewer, application-drafting, decision CLI, decision dashboard, cover-letter route, and their runtime storage interfaces. Existing legacy SQLite rows are retained but no longer accessed.

## Recent History From Git

- `cc93489` added two-layer filtering, matching the current project-gate and role-level screening flow.
- `96758e6` added tests and cover-letter behavior.
- `63e31aa` added packaging files.
