# Pre-Cap Total and Empty Requirements Design

Date: 2026-07-27

## Goal

Make score caps understandable in the candidate workbench and prevent absent extracted requirements from creating false mandatory-requirement caps.

## Candidate Workbench

Add a `Pre-cap total` column immediately to the left of the existing component score columns.

- The agent-score row shows the sum of the stored component scores before any cap is applied.
- The correction row shows the sum of the currently displayed component scores, including active saved corrections and the correction being typed.
- The pre-cap total is informational and is not directly editable.
- The overall score continues to apply active caps after calculating the pre-cap total.

The browser preview logic must update both the pre-cap total and the capped overall score from the same merged component values.

## Requirement Matching

Do not create a `RequirementMatch` for an extracted requirement whose value contains no requirement:

- `null`
- an empty or whitespace-only string
- an empty list
- an empty object
- a requirement object whose evidence is empty and whose only other values are empty

Non-empty scalar, list, and object requirements keep their current matching behavior. Explicit non-empty mandatory requirements can still activate `mandatory_requirement_not_met`.

## Existing Candidate Data

After the matcher change is verified, overwrite and rebuild candidate scores for `2026-07-27` using the existing `rescore-candidates` command. Confirm that `The Decision — Nurse` no longer has a false union-status mismatch or the corresponding 15-point cap.

## Testing and Verification

- Add matcher tests covering null and empty requirement shapes.
- Add candidate-workbench tests covering the new column, stored pre-cap total, and live-preview calculation.
- Run the targeted matcher, scoring, UI, and agent-scoring tests.
- Run the complete test suite because the change crosses extraction, matching, scoring display, storage-backed rescoring, and browser-visible UI behavior.
- Inspect the rebuilt Nurse candidate in SQLite.
- Reload and inspect the live `/candidates` page for July 27.

## Documentation

Update `CHANGELOG.md` and `PROJECT_STATE.md` because the matcher and candidate-workbench behavior are user-visible. No architecture document change is needed because module boundaries and system flow remain unchanged.
