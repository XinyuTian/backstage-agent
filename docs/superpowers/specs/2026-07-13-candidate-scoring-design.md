# Candidate-First Mutual Selection Scoring Design

## Purpose

Replace the current job selection shape:

```text
Jobs -> LLM Filter -> Apply
```

with a candidate-first scoring loop:

```text
Jobs
  -> Candidate Generation
  -> LLM Feature Extraction
  -> Local Requirement Matching
  -> Deterministic Scoring
  -> Re-ranking
  -> Human Feedback
  -> Approved Scoring Improvements
```

The new system must always produce a score for each candidate. It should not
silently filter projects or roles before they can be reviewed, scored, stored,
ranked, or corrected.

## Design Principles

- Always produce a score instead of a primary apply/reject decision.
- Treat casting as mutual selection: the candidate must meet the project's
  requirements, and the project must meet the actor's requirements.
- Use the LLM for structured feature extraction, not scoring.
- Use local rules and stored actor facts to evaluate project/role requirements.
- Improve the scoring function and scoring configuration, not the prompt, when
  human feedback shows a scoring mistake.
- Keep drafting/application as a separate human-approved workflow downstream of
  ranking.
- Keep project evaluation, but make it a scoring component instead of a hard
  project-level gate.

## Pipeline

1. Ingest recent Backstage jobs from the existing email and page parsing flow.
2. Parse projects and explicit roles.
3. Generate candidates:
   - `role` candidates for every explicit parsed role.
   - `project_only` candidates when roles are missing, vague, or the project
     itself is the opportunity.
4. Extract structured features with the LLM:
   - project facts
   - role facts
   - stated requirements
   - evidence snippets
   - uncertainty flags
5. Match project/role requirements against local actor capability and preference
   data.
6. Score with deterministic Python logic and versioned scoring rules.
7. Re-rank candidates with small deterministic workflow adjustments.
8. Display ranked bands.
9. Suggest drafts for top candidates without automatically drafting or applying.
10. Record human feedback as structured calibration data.
11. Aggregate feedback into user-approved scoring proposals.

## Candidate Model

Every parsed opportunity becomes a candidate record. The exact persistence shape
can evolve during implementation, but the stable conceptual model is:

```text
candidate_type: role | project_only
source_project_id
source_role_id
features_json
requirement_match_json
score_json
overall_score
score_band
rank_position
draft_suggestion
scoring_version
created_at
updated_at
```

`source_role_id` is optional for `project_only` candidates.

## Mutual Selection Model

Each candidate is evaluated in two directions.

### Their Requirements

This asks: do I meet what the project or role requires?

Examples:

```text
instagram_profile_share
ethnicity_or_nationality
gender
age_range
language
union_status
location
availability
travel
special_skills
```

The LLM may extract that a listing requires Instagram sharing, but local data
must decide whether the actor can do that. Stored local facts and preferences
should answer requirement checks whenever possible.

Requirement match statuses:

```text
met
not_met
unknown_needs_user_input
not_applicable
```

Mandatory unmet requirements become score caps. Preferred, contextual, or
unknown requirements become weighted scoring features.

### My Requirements

This asks: does this opportunity meet the actor's goals, constraints, and
preferences?

Examples:

```text
career_goal_alignment
role_value
project_value
pay
distance
time_burden
schedule
safety_or_personal_boundaries
public_performance
footage_or_portfolio_value
networking_value
```

These are scored as weighted components. Hard personal boundaries can also cap
the final score.

## Feature Extraction

The LLM should output structured features and evidence only. It should not output
the final score, score band, draft recommendation, or apply/reject decision.

Example feature shape:

```text
candidate_features:
  role_type: scripted_acting
  age_requirement: 20s-30s
  gender_requirement: female
  ethnicity_or_nationality_requirement:
    required: false
    preferred_or_contextual: true
    evidence: "..."
  compensation:
    type: paid
    amount: unknown
  project_signals:
    has_public_performance: true
    student_film: false
    brand_or_org_quality: medium
  requirements:
    instagram_profile_share:
      required: true
      evidence: "..."
  uncertainty:
    compensation_missing: true
    role_details_sparse: false
```

Prompt changes should be reserved for extraction failures, such as missing a
requirement, hallucinating evidence, or returning invalid schema. Scoring
mistakes should be fixed in the scoring function or scoring rules.

## Scoring

Scoring should be deterministic Python logic driven by a versioned
`scoring_rules.json` or equivalent configuration.

Initial component weights:

```text
their_requirements_match: 0-30
my_goal_alignment: 0-25
role_value: 0-15
project_value: 0-10
logistics: 0-10
compensation: 0-5
evidence_quality: 0-5
```

The score output should include a trace:

```text
overall_score: 86
score_band: strong_candidate
subscores:
  their_requirements_match: 27
  my_goal_alignment: 21
  role_value: 14
  project_value: 9
  logistics: 8
  compensation: 3
  evidence_quality: 4
score_caps: []
positive_drivers:
  - explicit scripted acting role
  - public performance
  - Instagram sharing requirement is locally marked okay
negative_drivers:
  - compensation amount unknown
score_trace:
  instagram_profile_share:
    status: met
    points: 4
    evidence: "..."
```

## Score Caps And Hard Constraints

Hard constraints still produce visible scores. They must not silently remove
candidates from storage, ranking, or feedback.

Initial score caps:

```text
mandatory_requirement_not_met: cap at 15
hard_personal_boundary: cap at 10
expired_or_unavailable: cap at 20
missing_critical_data: cap at 60
```

Example:

```text
overall_score: 7
score_band: not_worth_applying_today
score_caps:
  - hard_personal_boundary
cap_evidence:
  - "..."
```

## Score Bands

Score bands are presentation bands, not logical gates:

```text
90-100 top_priority
75-89 strong_candidate
60-74 maybe_review
40-59 low_priority
0-39 not_worth_applying_today
```

A low-scoring candidate remains reviewable and can receive feedback.

## Re-ranking

The first version of re-ranking should be deterministic and modest. The score
remains the main truth, but close candidates can be reordered for daily workflow
usefulness.

Potential adjustments:

```text
urgency_adjustment
freshness_adjustment
uncertainty_penalty
same_project_grouping_adjustment
```

Adjustments should be capped, for example to `+/- 5`, so a low-score candidate
cannot jump above a clearly stronger candidate because of a ranking tweak.

## Draft Suggestions

Scoring does not grant permission to apply.

The system may mark high-ranking candidates with `draft_suggestion: true`, but
drafting remains a downstream human-approved workflow. The initial version should
not auto-draft and should not submit live applications.

## Human Feedback

Human feedback should be lightweight but structured:

```text
candidate_id
agent_score
human_score
score_delta
affected_components
failure_modes
free_text_reason
calibration_status
created_at
```

Example:

```text
Job 13
Agent score: 86
Human opinion: should be 45
Reason: Nationality over-weighted.

affected_components:
  - identity_match
failure_modes:
  - overweighted_signal
```

## Error Taxonomy

The taxonomy should describe both the affected component and the failure mode.

Affected components:

```text
career_value
role_fit
identity_match
project_quality
compensation
logistics
schedule
evidence_quality
parser_quality
personal_boundary
their_requirements_match
my_requirements_match
```

Failure modes:

```text
overweighted_signal
underweighted_signal
missing_signal
hallucinated_signal
wrong_extraction
stale_or_incomplete_data
score_cap_too_harsh
score_cap_too_weak
unclear_preference
```

This prevents every new mistake from becoming another one-off prompt rule.

## Scoring Improvement Loop

The system should aggregate human feedback and propose scoring changes. It should
not automatically mutate scoring rules.

Example proposal:

```text
Pattern:
  identity_match + overweighted_signal
  4 examples
  average human correction: -28

Proposal:
  reduce contextual identity boost from +10 to +3
  only award full identity points when the listing states a requirement
```

Approved proposals update the scoring configuration and increment
`scoring_version`. Rejected proposals remain as historical calibration data.

## Migration Notes

The current system already has structured screening artifacts, project-level
screening, role-level screening, final buckets, reviewer artifacts, storage, and
dashboard views. The new design should use those as migration context, but not
preserve the current bucket model as the long-term architecture.

Implementation should be incremental:

1. Add candidate/scoring data structures and tests.
2. Add LLM feature extraction schemas that do not include scores.
3. Add local requirement matching against actor capability/preference data.
4. Add deterministic scoring and score traces.
5. Store and display ranked candidates.
6. Add draft suggestions.
7. Add human feedback capture and taxonomy.
8. Add calibration proposal generation.
9. Retire or compatibility-wrap legacy decision buckets after the scoring view is
   trusted.

## Non-goals For The First Implementation

- No live Backstage submission.
- No automatic scoring-rule mutation.
- No automatic project-level filtering.
- No inferred roles beyond parsed explicit roles and project-only opportunities.
- No learning-to-rank model beyond small deterministic re-ranking adjustments.

