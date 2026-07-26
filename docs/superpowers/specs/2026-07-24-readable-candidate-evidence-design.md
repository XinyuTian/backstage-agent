# Readable Candidate Evidence Design

Date: 2026-07-24

## Goal

Present enough source-grounded information to make an application decision
without the visual fatigue of nested JSON labels, repeated numbered headings,
bold-heavy typography, or multi-column evidence cards.

## Reading Model

The right-panel evidence area is a single vertical reading flow. It does not
use multiple evidence columns or side-by-side label/value grids.

Section names and order are adaptive rather than mechanically fixed. The
renderer may omit empty sections, combine closely related facts, and order
sections by decision value. A typical flow is:

1. Role description and role type.
2. Project description and project type.
3. Where and when production happens.
4. Compensation, union status, and other practical terms.
5. Requirements as a plain bullet list.
6. Requirement-match or decision-relevant notes.
7. Collapsed original listing text.

## Typography

- Use normal-weight body text.
- Reserve bold or semibold type for the candidate title and small section
  labels.
- Use subdued labels, generous line height, and thin separators.
- Do not render wrapper labels such as `Requirement 1`, `Requirement 2`,
  `Requirement Key`, or repeated nested object keys.
- Keep each section in the same content column.

## Content Rules

- Use only stored listing, extracted feature, and requirement-match data.
- Do not invent project or role descriptions.
- Prefer concise readable sentences where the source fields support them.
- Preserve source evidence for individual requirements when useful, but do not
  repeat the same wording unnecessarily.
- Show shooting locations and dates from stored project/role data or extracted
  source content.
- Show compensation and production terms when available.
- Show decision-relevant match status and reasons in plain language.
- Omit empty or low-value technical containers such as raw extraction wrappers.
- Keep the full original listing text in a collapsed disclosure at the bottom.

## Original Text

The disclosure uses the best available stored source text, preferring the
listing's `raw_text` and falling back to `description`. It is collapsed by
default and rendered as readable pre-wrapped text.

## Scope

Keep the existing header, filters, adjustable 22/78 workbench, score, correction
grid, date navigation, correction persistence, and scoring behavior unchanged.
No storage schema or extraction-prompt changes are required.

## Testing and Verification

- Add focused renderer tests for flattened requirements and omission of
  numbered wrapper headings.
- Verify evidence is a single column.
- Verify empty sections are omitted.
- Verify role, project, logistics, compensation, requirements, decision notes,
  and original text render from representative stored payloads.
- Run candidate UI tests and the full suite.
- Restart and visually inspect the live subject-date dashboard.
