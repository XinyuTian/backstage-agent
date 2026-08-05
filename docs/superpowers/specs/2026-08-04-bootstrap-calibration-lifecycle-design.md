# Bootstrap Calibration Lifecycle Design

Date: 2026-08-04
Status: Approved design

## Goal

Make scoring calibration responsive during the system's early learning stage without allowing repeated feedback or earlier rule adjustments to push the same metric repeatedly. Preserve all feedback as auditable history while treating only the latest feedback for a role and metric as the active human label.

## Current Problem

The current `calibration-patterns` command aggregates every qualifying feedback row and every current component correction each time it runs. Candidate feedback has a `calibration_status` field, but the runtime never updates or filters on it. Calibration proposals are inserted on every run without deduplication. Consequently, the same evidence can generate repeated proposals, and repeated feedback about one role can be counted as though it came from independent roles.

Dashboard component corrections already use one stable row per candidate identity and component. A later correction overwrites the active value, but the system does not retain correction history or associate calibration evidence with scoring-rule versions.

## Behavioral Contract

### Latest Active Label

- The calibration evidence unit is one role and one scoring component.
- Only the latest human feedback for that role/component pair is active.
- A newer submission supersedes the earlier active submission for calibration purposes.
- Superseded feedback remains stored for audit history and is never counted as another independent example.
- Distinct roles, rather than submission count, determine evidence volume.

Project-only candidates use the same rule with their stable project candidate identity in place of a role identity.

### Versioned Cumulative Residuals

Historical active labels remain reusable. They are not permanently consumed or deleted after one calibration run.

Before proposing another adjustment, the system evaluates each active label against the current scoring-rule version. Its calibration signal is the residual between the human target and the score produced by the current rules. When an earlier rule adjustment already corrected an example, that example's residual approaches zero and no longer pushes the metric in the same direction.

### Historical Weight Decay

Active evidence from different candidates does not remain equally influential forever. After residual recomputation, calibration multiplies each residual by an auditable age weight based on the evidence submission time:

| Evidence age at calibration | Weight |
|---|---:|
| 0-30 days | 1.00 |
| 31-90 days | 0.70 |
| 91-180 days | 0.40 |
| More than 180 days | 0.20 |

Superseded evidence for the same candidate/component has weight zero. When a component has at least five active labels submitted within the last 30 days, active evidence older than 90 days becomes stability-only evidence: it remains visible in the calibration report but has weight zero in the proposed adjustment. This lets sufficiently dense new information replace stale market or role patterns quickly without erasing history.

The proposed adjustment uses the weighted mean residual, `sum(residual * weight) / sum(weight)`, rounded to the nearest integer and then bounded by the maturity-stage adjustment cap. Raw distinct-candidate count continues to determine maturity; both raw count and effective weight sum are reported. The calibration run date and each applied weight are stored with proposal evidence so results are reproducible.

Every calibration run records:

- the scoring-rule version evaluated;
- the active feedback records supporting the proposal;
- the residual summary;
- the calibration date, evidence age, and applied historical weight;
- the raw evidence count and effective weight sum;
- the evidence count based on distinct candidate identities;
- the calibration maturity stage;
- the proposed adjustment and its review status.

This provides repeat-run idempotence: running calibration again with the same rules and evidence must not create a new equivalent proposal.

## Bootstrap-First Adjustment Policy

Calibration begins aggressively because the initial scoring rules are expected to need substantial correction. It becomes more conservative as evidence for an individual metric grows.

| Stage | Active distinct candidates for metric | Maximum proposed adjustment | Review policy |
|---|---:|---:|---|
| Bootstrap | 1-5 | plus or minus 5 points | Manual approval required |
| Learning | 6-15 | plus or minus 3 points | Manual approval and directional-consistency check |
| Mature | 16 or more | plus or minus 2 points | Manual approval, stronger consistency check, and outlier-resistant summary |

The evidence count and maturity stage are component-specific. A mature `role_value` component does not force a newly reviewed `identity_match` component out of bootstrap mode.

The initial implementation delivers the bootstrap stage only. Learning and mature behavior remain documented as planned work rather than being approximated with unreviewed heuristics.

## Persistence Model

The storage design must distinguish immutable submissions from their active calibration interpretation.

### Feedback identity and supersession

Candidate feedback must be resolvable to stable candidate identity fields:

- `candidate_type`;
- `project_key`;
- normalized `role_key`;
- affected component.

For multi-component legacy CLI feedback, each component is interpreted independently. A new submission supersedes only matching role/component evidence, not unrelated components from the same feedback row.

Supersession is represented in a normalized, append-only `candidate_calibration_evidence` table rather than by destructive deletion. Each row stores the stable candidate identity, one affected component, the human target, submission metadata, and an optional `superseded_at` timestamp. Inserting new evidence marks the prior active row for the same stable candidate/component as superseded in the same transaction. A partial unique index permits only one row with `superseded_at IS NULL` for each stable candidate/component identity. Candidate row IDs remain traceability fields, not calibration identity, because they can change during rescoring.

Existing dashboard corrections are migrated into this evidence table without removing the correction rows used by the workbench display. New dashboard saves append evidence and continue updating the existing correction overlay. Existing coarse `candidate_feedback` rows are normalized component-by-component during a migration; the original rows remain intact as audit sources.

### Calibration runs and proposal evidence

A calibration run or proposal-evidence relation must record which active labels were evaluated. Proposal identity must include at least:

- pattern/component key;
- evaluated scoring version;
- evidence-set fingerprint or equivalent stable identity.

An equivalent run must update or return the existing proposal instead of inserting a duplicate.

The existing human-readable statuses `proposed`, `accepted`, and `rejected` remain proposal review states only. Feedback itself does not need a user-facing status vocabulary; it is either the latest active label or superseded history.

## Calibration Flow

1. Load the latest active human label for every stable candidate/component pair.
2. Group labels by scoring component. Taxonomy failure modes remain supporting diagnostics, not independent evidence multipliers.
3. Resolve the current scoring-rule version.
4. Recompute, or derive through the production scoring path, the current component result for each labeled candidate.
5. Calculate each residual from the human target and current component result.
6. Apply the age-based weight and the recent-evidence stability-only rule.
7. Determine maturity from the raw number of distinct active candidates for the component.
8. Generate a bounded proposal from the weighted mean residual using the stage policy.
9. Record the proposal, calibration date, weights, and exact evidence set idempotently.
10. Require manual review before modifying `scoring_rules.json`.
11. After an accepted rule change, rescore the same active evidence under the new version before any later proposal is generated.

## Safety and Error Handling

- Feedback tied to candidates that cannot be reconstructed under the current scoring contract remains historical but is excluded with an explicit reason.
- Stale scoring snapshots must not be silently compared with current rules.
- A repeated command with no changed evidence or scoring version must report that no new proposal is needed.
- A different calendar date alone must not create a duplicate proposal unless at least one evidence item crosses a defined age boundary and therefore changes the weighted calculation.
- A new feedback submission for an existing role/component replaces the active label even if an older proposal referenced the previous submission.
- Calibration must not mutate production scoring rules automatically.
- Database migrations must preserve all existing candidate feedback and component corrections.

## CLI and Dashboard Scope

The `calibration-patterns` command remains the manual trigger. Its output should distinguish:

- active evidence count;
- effective evidence weight and stability-only count;
- excluded or superseded evidence count;
- maturity stage;
- current residual;
- proposed bounded adjustment;
- whether the proposal is new or already recorded.

Dashboard proposal review and automatic rule-file rewriting are outside the initial implementation. Existing correction entry and corrected-score display behavior must remain unchanged.

## Testing

Storage tests must prove that:

- two submissions for the same role/component yield one active label;
- the latest submission wins;
- earlier submissions remain queryable as history;
- feedback for different components or roles remains independent;
- rescored candidate row IDs do not create duplicate active evidence;
- equivalent evidence and scoring versions do not create duplicate proposals.

Calibration tests must prove that:

- bootstrap evidence permits an adjustment bounded at five points;
- residuals are calculated against current rules;
- evidence receives weights of 1.00, 0.70, 0.40, or 0.20 at the specified age boundaries;
- evidence older than 90 days receives zero proposal weight when at least five recent labels exist;
- weighted residuals, rather than unweighted averages, determine the proposal;
- an accepted earlier adjustment reduces later residual pressure;
- evidence counts use distinct stable candidate identities;
- missing or incompatible scoring evidence is excluded explicitly.

CLI tests must prove that repeated calibration with unchanged inputs reports no new proposal rather than duplicating one.

## Documentation and Future Plan

`PROJECT_STATE.md` should identify bootstrap calibration as the current behavior and list learning/mature calibration as future work. `CHANGELOG.md` should record the new feedback supersession, versioned evidence, and idempotent proposal behavior. README command documentation should explain that calibration retains history and uses only the latest active label per role/component.

Future work will implement the learning and mature stages, including directional-consistency thresholds, median or trimmed residual summaries, and historical evaluation of proposed rule changes before approval.

## Non-Goals

- Deleting historical feedback.
- Counting repeated submissions for one role as independent evidence.
- Automatically accepting proposals or rewriting scoring rules.
- Retraining the feature-extraction LLM.
- Building dashboard proposal-review controls in the initial implementation.
