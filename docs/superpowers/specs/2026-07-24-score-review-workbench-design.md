# Score Review Workbench Design

## Purpose

The candidate dashboard is an English review workbench for comparing extracted listing evidence with deterministic component scores. It replaces the card wall with a date-ordered candidate list and one selected detail pane.

## Score ownership

Each candidate keeps three distinct score concepts:

- **Agent score:** the immutable output stored on the `candidates` row.
- **Current correction:** one optional override for one stable candidate identity and component.
- **Displayed score:** agent subscores overlaid with active corrections, then recomputed with the candidate's saved caps and band thresholds.

Corrections never mutate official score, band, rank, cap, or draft-suggestion fields.

## Correction identity and lifecycle

`candidate_score_corrections` is keyed by:

```text
candidate_type + project_key + role_key + component_name
```

Project-only candidates use an empty `role_key`. `candidate_id_at_submission` is audit metadata, not identity, so overwrite rescoring can replace candidate rows without orphaning the current correction.

Saving a component again overwrites only that component. Each component has its own optional reason and independent Save and Reset actions. Calibration counts the current correction once, regardless of how many times it was edited. Existing coarse `candidate_feedback` CLI rows remain append-only and separate.

## Scoring compatibility

Every newly scored candidate snapshots resolved component maxima, cap values, and band thresholds in `score_json`. Production scoring and corrected display scoring use the same Python recomputation helper.

When a new candidate scoring version appears:

- a correction remains active when its component maximum is unchanged and the UI shows a version warning;
- a correction becomes stale when its component maximum changed;
- stale corrections do not affect displayed Overall until Reconfirm;
- Reset removes the current component correction.

## Layout

- Left: candidates ordered by effective project date descending.
- Right top: independently scrolling listing text, extracted features, requirement matches, drivers, and score trace.
- Right bottom: pinned component rows with Agent, Correction, optional Reason, and actions.
- Overall is read-only and previews the merged score.
- Active caps are visible but not editable.

## Out of scope

- Editing caps.
- Automatically changing `scoring_rules.json`.
- Correction history UI.
- User-selectable sorting.
- Recomputing agent rank or draft suggestion from corrections.
- Live Backstage or model-provider actions.
