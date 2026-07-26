# Compact Candidate Workbench Design

Date: 2026-07-24

## Goal

Make `/candidates` compact and comfortable for daily review while preserving the current correction persistence and scoring behavior.

## Page Structure

- Restore the green `Backstage Candidates` header from the pre-workbench UI.
- Show only the title in the header; remove the subtitle.
- Put a single compact filter row immediately below the header.
- Keep the existing left-list/right-detail workbench.
- Preserve `Project name — Role name` in both the list and detail heading.

## Filters and Dates

The filter row, from left to right, contains:

1. An unlabeled project/role search input.
2. An unlabeled date input.
3. A previous-day arrow.
4. `Today`.
5. A next-day arrow.
6. `7 days`.
7. The filter action.

The default date mode is one exact day. The arrows move that day backward or
forward, `Today` selects the current local date, and `7 days` shows the
seven-day window ending on the selected date. The selected date/mode remain in
candidate links and correction redirects.

The candidate date comes from the Backstage email subject, such as
`4 New Roles Available for basic filter - Jul 23`, producing `2026-07-23`.
Workbench queries and ordering use the stored subject-derived `project_date`
before ingestion timestamps such as `last_seen_date` or `created_at`.

## Right Detail Panel

The heading contains only:

- `Project name — Role name`
- the numeric score

Remove candidate-type eyebrow text, `Overall`, score-band text such as
`Low priority`, the compatible-snapshot banner, `Listing`, active-cap content,
and instructional copy.

The upper scrollable area shows extracted features and relevant extracted
information in readable compact typography. It does not show internal scoring
traces, positive/negative driver cards, or raw listing wrappers.

## Correction Grid

Anchor a plain spreadsheet-like table to the bottom of the right panel so the
upper area receives the remaining vertical space.

- Components are columns.
- The first row is `Agent score`.
- The second row is `Your correction`.
- Each correction cell combines a numeric corrected-score input with a compact
  feedback/reason input.
- Editing the score makes its feedback input available.
- Pressing Enter saves that component correction.
- Existing corrections remain editable and resettable without changing the
  official stored candidate score.
- Stale or incompatible corrections retain their existing safety behavior, but
  warnings and actions use compact cell-level treatment instead of banners.
- The grid may scroll horizontally when the panel is too narrow.

## Data and Error Handling

- Extend the candidate workbench search query with exact-date and seven-day
  filters; do not change candidate scoring or persistence schemas.
- Continue server-side validation of correction ranges, candidate identity,
  component names, and scoring-snapshot compatibility.
- Invalid correction submissions return the existing HTTP 400 behavior.
- Existing correction storage remains the source of truth.

## Tests

Add or update targeted tests for:

- subject-derived `Jul 23` becoming `2026-07-23`;
- project-date precedence in workbench rows;
- exact-day and seven-day storage filtering;
- previous/next/today/7-day controls and retained query context;
- compact header and removed labels/banners/sections;
- two-row spreadsheet markup and Enter-to-save behavior;
- existing correction save, reset, reconfirm, and validation behavior.

Run the targeted parser, candidate-storage, and candidate-UI suites. Run the
full suite because the change crosses parsing, storage, and UI boundaries.

## Non-Goals

- No scoring-rule or score-calculation changes.
- No SQLite schema migration.
- No changes to daily scan scheduling or notification behavior.
- No live Backstage submission or other external action.
