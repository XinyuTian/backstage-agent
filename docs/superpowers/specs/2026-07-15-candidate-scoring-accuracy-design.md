# Candidate Scoring Accuracy and Calibration Design

## Status

Approved in conversation on 2026-07-15.

This design refines the candidate-first mutual-selection architecture in
`2026-07-13-candidate-scoring-design.md`. It preserves the principles that the
LLM extracts facts, Python performs local matching and deterministic scoring,
and human feedback produces reviewable calibration proposals. It supersedes
the earlier design's initial component weights, universal mandatory-requirement
cap, and detailed-feedback-first dashboard interaction.

Implementation depends on a separately designed incremental storage refactor
that gives projects, roles, requirements, evaluations, and profile facts clear
durable boundaries. This document defines downstream scoring requirements for
that database project; it does not define the database schema or migration.

## Goal

Improve ranking accuracy while balancing false positives and false negatives,
with a conservative bias at the top of the ranking:

- borderline opportunities may remain visible in middle and lower bands;
- candidates at 75 or above should rarely be obviously unsuitable;
- candidates at 90 or above require strong evidence and no unresolved critical
  requirement;
- missing data must not be treated as a confirmed mismatch;
- stored actor facts should answer repeat questions whenever possible.

The daily human-calibration budget is approximately five minutes. The system
should minimize low-value interruptions, but there is no hard limit on the
number of decision-critical questions it may ask.

## Design Principles

- Stabilize data contracts before tuning weights.
- Treat extraction confidence, requirement status, raw quality score, and score
  limits as separate concepts.
- Apply a severe score limit only to an explicit, reliably evaluated hard
  mismatch.
- Preserve original listing evidence for every extracted requirement and every
  score explanation.
- Prefer durable local rules and stored profile facts over repeated LLM or user
  judgments.
- Collect lightweight human judgments before asking for detailed taxonomy.
- Never change scoring rules automatically from a single feedback example.
- Compare scoring versions on the same historical examples before promotion.

## Phase 1: Canonical Requirements and Reliable Local Matching

### Canonical requirement contract

Every extracted requirement must be normalized to a stable record such as:

```json
{
  "category": "age",
  "value": {"min": 60, "max": 80},
  "required": true,
  "evidence": "Male, 60-80",
  "source": "role_description",
  "confidence": 0.98
}
```

The category must come from a documented enum. Generic keys such as
`requirement_1` are invalid normalized output. A plain string must not become a
hard requirement merely because of its data type. `required` must be grounded
in listing language or explicit casting constraints. Confidence describes the
reliability of extraction, not whether the actor satisfies the requirement.

### Initial normalized categories

The first implementation must cover at least:

- gender or playing-gender requirement;
- age or playing-age range;
- union status;
- location and local-hire requirement;
- dated availability;
- objective appearance attributes;
- performance direction and required skills;
- languages;
- social-media obligations;
- safety and personal-boundary requirements.

Subjective performance language should usually be a soft role signal, not a
personal-fact question. Appearance requirements should separate objective facts
such as beard or hair color from subjective descriptions such as warm or
grandfatherly.

### Match statuses

Replace the overloaded `needs user input` presentation with:

```text
confirmed_match
confirmed_mismatch
not_yet_verified
not_applicable
```

Only `confirmed_mismatch` is negative evidence. `not_yet_verified` means that
the system lacks a reliable local answer and must not be treated as a rejection.

### Hard-limit eligibility

A hard mismatch may limit the final score only when all three conditions hold:

1. the listing explicitly makes the requirement mandatory;
2. local data provides a reliable, applicable answer; and
3. normalized comparison produces a confirmed mismatch.

Missing rules, missing profile facts, low extraction confidence, soft
preferences, or formatting differences such as `nonunion` versus `non-union`
must not trigger a confirmed-mismatch limit.

## Phase 2: Deterministic Scores, Confidence Limits, and Ranking

### Component weights

```text
their_requirements_match: 0-35
my_goal_alignment:        0-20
role_value:               0-15
project_value:            0-10
logistics:                0-10
compensation:             0-5
evidence_quality:         0-5
total:                    0-100
```

The increased requirements component supports conservative high-score
precision without reducing mutual selection to eligibility alone.

### Requirement credit

Within `their_requirements_match`, requirement importance uses an initial
relative weighting of:

```text
explicit hard requirement: 3
ordinary requirement:      2
preference or bonus:        1
```

Statuses receive the following treatment:

- `confirmed_match`: full allocated credit;
- `confirmed_mismatch`: zero credit and possible hard limit;
- `not_yet_verified`: approximately 25 percent provisional credit;
- `not_applicable`: removed from the denominator.

The exact rounding and allocation algorithm must be deterministic and covered
by tests.

### Confirmed-mismatch limits

Initial limits are category-specific rather than universal:

```text
explicit gender or age mismatch: max 20
explicit union-eligibility mismatch: max 25
confirmed date unavailability: max 10
hard personal boundary: max 0
expired or closed opportunity: max 0
confirmed missing mandatory skill: max 30
```

These values are initial policy subject to offline evaluation and approved
calibration. Every limit must name its category and supporting evidence.

### Evidence-confidence limits

Unknown data is not a mismatch, but it can prevent an unverified candidate from
entering a high-confidence band:

```text
one or more unresolved critical requirements: max 89
more than half of hard requirements unverified: max 74
severely sparse role information: max 59
feature extraction failure: Data Error, not a normal score
```

The score output and UI must display raw component total, final score, and every
applied limit separately.

### Bands and draft suggestions

```text
90-100: top_priority
75-89:  strong_candidate
60-74:  maybe_review
40-59:  low_priority
0-39:   not_worth_applying_today
```

A draft suggestion requires a final score of at least 90, no confirmed hard
mismatch, no unresolved critical question, and sufficient evidence quality.

### Re-ranking

The displayed score represents candidate quality. Workflow re-ranking may add
at most a small adjustment, initially no more than plus or minus three points,
for urgency or similar workflow factors. Re-ranking must never allow urgency to
overpower a material quality difference.

## Phase 3: Dynamic Questions and Five-Minute Human Feedback

### Daily review sample

The dashboard should select approximately five to ten items for review:

- the day's top five;
- candidates near the 60, 75, or 90 thresholds;
- candidates with high-value unresolved questions;
- low-confidence candidates that may still be valuable; and
- a small random sample from lower ranks to detect false negatives.

### Quick feedback

The primary interaction is one of:

```text
too_high
about_right
too_low
not_enough_information
```

Exact human score is optional. Detailed taxonomy is requested only after a
disagreement, using controlled choices such as extraction error, missing
profile fact, false match, false mismatch, weight too high, weight too low,
incorrect score limit, or missing personal preference.

The daily flow should also include a small number of pairwise comparisons among
close-ranked candidates:

```text
prefer A
prefer B
prefer neither
```

### Dynamic question priority

There is no fixed daily question cap. Questions are prioritized as:

1. `decision_critical`: may cross an action threshold, add or remove a hard
   limit, affect a top-five candidate, or answer several candidates at once;
2. `useful_for_calibration`: reusable profile facts that do not change today's
   action; and
3. `low_value`: subjective, one-off, or immaterial questions that should not be
   asked.

All decision-critical questions may be asked, even when there are more than two.
Duplicate questions across roles must be merged, and the UI should show how many
candidates an answer affects. Skipping, answering `I do not know`, or postponing
must not be recorded as `No`.

### Profile-fact lifetime

Answers must have an explicit scope:

```text
permanent
long_lived
current_appearance
date_specific
opportunity_only
```

Stored answers are reused until their scope expires or the user changes them.

### Calibration proposals

A single correction records evidence but does not mutate rules. Repeated
patterns, initially at least three comparable examples, may generate a proposal.
The proposal must show supporting examples, replay old and proposed rules on the
benchmark set, and require explicit approval before changing scoring behavior.

## Phase 4: Offline Evaluation and Safe Promotion

### Benchmark set

Start with approximately 40 historical roles and grow beyond 100 through daily
feedback. The set must span score bands, project types, requirement categories,
data-quality levels, known errors, and lower-ranked opportunities that may be
false negatives.

Human labels should include:

```text
would_apply | maybe | would_not_apply
human_score_band
confirmed_blockers
incorrect_extracted_facts
missing_profile_facts
```

Exact numeric scores are optional.

### Primary metrics

Initial evaluation targets are:

- high-score false-positive rate below 5 percent for scores of 75 or above;
- zero known confirmed hard mismatches at 75 or above;
- rolling Precision@5 of at least 80 percent;
- Recall@10 of at least 80 percent for `would_apply` opportunities;
- pairwise-order agreement of at least 80 percent;
- NDCG@10 for comparing whole ranked lists; and
- data-quality coverage and question-efficiency metrics.

These are initial gates. They should be revisited after two weeks of real
baseline data, not weakened merely to permit a release.

### Time-based holdout

Older examples may be used to tune rules. Newer examples must remain a holdout
set so a version is tested on data gathered after its tuning examples.

### Replay and promotion

Every scoring-rule change must replay the same benchmark and report:

- old and new metrics;
- improved and regressed examples;
- all band changes; and
- new schema or data errors.

A new version must not promote when high-score false positives increase, known
hard-mismatch regressions fail, or data errors appear, even if the average score
metric improves.

New and current versions run side by side in shadow mode. The current version
continues to drive the default ranking while the proposed version displays its
score and reasons for comparison. Promotion requires repeated daily review and
explicit user approval. Previous versions remain reproducible and available for
rollback.

### Failure behavior

- Invalid LLM feature output becomes `Data Error`, not a zero score.
- An unknown local rule becomes `not_yet_verified`, not mismatch.
- Failed rescoring preserves the last valid score rather than overwriting it.
- Expired profile facts become questions rather than inferred negative answers.
- Sparse evidence limits confidence but must not invent facts.
- Each result records source evidence, normalized requirements, profile snapshot,
  extraction version, and scoring version.

## Database Refactor Dependency

Before implementing this design, define an incremental storage model that at
minimum separates:

- projects from roles;
- project requirements from role requirements;
- project evaluations from role evaluations;
- source facts from derived matches and scores;
- scoring runs and versions from current displayed results; and
- reusable profile facts from opportunity-specific answers.

The refactor must preserve raw source data, use versioned migrations or an
equivalent auditable mechanism, backfill historical data safely, and support a
temporary dual-read or shadow path. A big-bang replacement of the active SQLite
database is outside this scoring design.

## Non-goals

- No live Backstage submission.
- No automatic mutation of scoring rules.
- No end-to-end LLM judge that controls the final score.
- No learning-to-rank model until the human-label set is sufficiently stable.
- No forced answer to low-value questions.
- No destructive one-step replacement of the existing database.

## References

- Google, Rules of Machine Learning:
  https://developers.google.com/machine-learning/guides/rules-of-ml
- Google, Recommendation systems overview:
  https://developers.google.com/machine-learning/recommendation/overview/types
- Google, Recommendation scoring:
  https://developers.google.com/machine-learning/recommendation/dnn/scoring
- TensorFlow Ranking:
  https://www.tensorflow.org/ranking
- Google Research, Towards Conversational Recommender Systems:
  https://research.google/pubs/towards-conversational-recommender-systems/
- Google Research, Offline Retrieval Evaluation Without Evaluation Metrics:
  https://research.google/pubs/offline-retrieval-evaluation-without-evaluation-metrics/
