# Role Selection Decision Core Design

Date: 2026-07-10

## Purpose

The current role selection system works, but daily tuning has started to create scattered one-off logic across local rules, LLM prompts, and profile fields. The redesigned system should preserve the existing three-filter workflow while making decisions easier to trust, tune, audit, and extend without editing code every morning.

The first implementation slice is the decision model: five final buckets, structured first-pass LLM output, downgrade-only reviewer validation, and deterministic bucket resolution. Dashboard grouping and preference-rule authoring follow after the decision contract is stable.

## Goals

- Preserve the current three-filter structure: local rules, first LLM screening, second LLM reviewer.
- Make the final role outcome one of five clear buckets:
  - `Auto Apply/Draft`
  - `Ready For Review`
  - `Needs My Preference`
  - `Reject`
  - `Data/Parse Error`
- Stop daily preference tweaks from becoming prompt/code patches.
- Keep objective hard rejects in tested Python code.
- Move preference policy, career-value scoring, examples, and bucket policy toward structured data.
- Make reviewer usefulness visible in the dashboard so the user can tell whether the second LLM is helping.
- Keep project-level and role-level decisions separate.

## Non-Goals

- Do not remove the second LLM reviewer.
- Do not implement live Backstage submission.
- Do not build full historical reviewer analytics in the first slice.
- Do not rewrite parser or dashboard architecture before the decision contract is stable.
- Do not make sparse notices fail just because they omit optional fields.

## Final Buckets

### Auto Apply/Draft

Use when the role is known-good:

- no objective hard reject
- no missing required preference
- enough evidence to support the classification
- career value supports applying
- reviewer did not provide an evidence-backed downgrade

Known allowed preferences do not block this bucket. Current examples include unpaid roles, horror, swimwear, kissing, pets/children, and active Instagram tagging when the corresponding profile facts allow them.

### Ready For Review

Use when the role is probably worth applying to, but the user should eyeball it:

- mild concerns
- reviewer downgrade from `Auto Apply/Draft`
- low confidence
- low-pay/high-burden cases that do not meet reject criteria
- useful opportunity with incomplete but non-blocking facts

This bucket should be a useful shortlist, not a junk drawer.

### Needs My Preference

Use when the notice requires a preference or comfort answer that the profile does not know yet.

Examples:

- requires a comfort boundary not yet answered
- requires a special ability or logistics fact that is not in the profile
- requires a reusable preference decision that should not be guessed

The dashboard should show the preference question plus provisional outcomes, such as:

- if yes: likely `Auto Apply/Draft` or `Ready For Review`
- if no: likely `Reject`

After the user answers, the answer is saved to `profile.json` and matching current roles are rescored immediately.

### Reject

Use for objective mismatches and clear career-goal mismatches.

Hard reject examples:

- explicit gender mismatch
- impossible age range
- native-English requirement when `english_native_speaker=false`
- real singing requirement when `can_sing=false`
- explicit avoid terms such as adult content or explicit nudity
- project-wide mission mismatch with the user's goal of starting a career in art/performing
- impossible location/date requirement

Low pay alone is not enough for reject. Low pay plus high burden and weak career value can reject.

### Data/Parse Error

Use when the system cannot produce a trustworthy decision because of parse, model, schema, or data failure.

Malformed LLM output gets one repair retry. If it still fails validation, the role becomes `Data/Parse Error`.

## Screening Order

The pipeline always screens projects before roles.

1. Parse project notices from the email digest.
2. Enrich each project from its Backstage page when available.
3. Run project-level local rules, first LLM screening, reviewer validation, and bucket resolution.
4. Continue to role-level screening only when the project bucket allows role screening.
5. Run role-level local rules, first LLM screening, reviewer validation, and bucket resolution for each role.
6. Application drafting only considers role-level `Auto Apply/Draft` outcomes.

Project-level decisions answer: "Should this project proceed to role selection?"
Role-level decisions answer: "Should this specific role be applied to or reviewed?"

## Three-Filter Workflow

### 1. Local Rules

Local rules remain fast deterministic checks. They should handle objective hard rejects and obvious system errors.

Responsibilities:

- gender, age, identity/language, native-English, singing, avoid-term checks
- project-wide mission mismatch checks
- known deterministic parse/data errors
- known preference facts when they are unambiguous

Local rules should not absorb every preference or career-value judgment. If a rule represents user policy rather than objective matching, prefer moving it into `screening_rules.json` unless it is a tested hard reject.

### 2. First LLM Screening

The first LLM becomes a structured classifier/advisor. It should return controlled JSON fields rather than free-form approval reasoning.

Required output fields:

- `suggested_bucket`
- `role_type`
- `project_type`
- `career_value_score` from 0 to 5
- `required_preferences`
- `missing_preference_keys`
- `pay_burden`
- `travel_burden`
- `time_burden`
- `fit_reasons`
- `concerns`
- `evidence_snippets`
- `confidence`

The first LLM may classify unclear role types into the controlled taxonomy. The parser extracts facts; the LLM classifies fuzzy meaning.

### 3. Second LLM Reviewer

The reviewer stays in the architecture, but becomes a downgrade-only validator.

Reviewer responsibilities:

- check whether the first LLM invented facts
- check whether it missed a hard reject
- check whether it missed a required preference question
- check whether `Auto Apply/Draft` is too optimistic
- check whether career value is supported by notice evidence

Reviewer output must be structured and evidence-backed.

The reviewer can downgrade only within these bounds:

- `Auto Apply/Draft` can become `Ready For Review`
- `Ready For Review` can become `Needs My Preference` or `Reject` only with explicit evidence
- hard rejects and missing required preferences are deterministic and do not depend on reviewer opinion

Reviewer disagreement only counts if it cites exact notice evidence. Vague disagreement does not change the bucket.

### 4. Deterministic Bucket Resolver

The resolver has final say. It combines:

- local rule result
- first LLM structured classification
- reviewer validation
- `profile.json`
- `screening_rules.json`

Resolution precedence:

1. System/model/schema failure after retry -> `Data/Parse Error`
2. Objective hard reject -> `Reject`
3. Missing required preference -> `Needs My Preference`
4. Evidence-backed reviewer downgrade -> safer allowed bucket
5. First LLM suggestion plus deterministic policy -> final bucket

## Profile And Rules

### profile.json

`profile.json` remains the durable actor profile. It stores personal facts and comfort answers:

- identity/profile facts
- age, gender, location, union status
- skills/training/credits
- stable comfort answers, such as `comfortable_with_kissing`
- ability facts, such as `can_sing`
- logistics facts, such as driving/car/passport details

When the user answers a `Needs My Preference` question, the reusable answer is saved here.

### screening_rules.json

Add a dedicated rules file for automation policy.

It should contain:

- five bucket definitions
- role-type taxonomy
- career-value scoring defaults
- known preference keys and labels
- preference examples for prompt generation
- which preferences become hard rejects when false
- low-pay/high-burden tradeoff rules
- reviewer downgrade constraints
- prompt-generation examples and instructions

Prompts should be assembled from `screening_rules.json` where possible, so future tuning edits data rather than Python prompt strings.

## Career-Value Scoring

Use a 0-5 score.

Default scale:

- `5`: scripted acting roles with named character, theater/film/TV/comedy/improv, meaningful scene work
- `4`: student/indie film with real acting, unpaid theater with good acting value, staged reading with real role
- `3`: commercial/UGC/testimonial with speaking or personality, music video with performance element, host/presenter work
- `2`: background/extra, audience member, atmosphere, generic social media appearance
- `1`: pure modeling/appearance, thirst trap/sensual content, brand promo with little acting
- `0`: adult/explicit content, explicit nudity, scams, senior/community mission mismatch, native-English/singing mismatch when required

Low pay alone should not reject a role. Low pay plus high burden and weak career value can reject.

## Project And Role Separation

Project gates should reject only project-wide conflicts:

- adult/explicit project-wide content
- impossible location/date
- project-wide native-English requirement
- project-wide mission mismatch
- unsafe or impossible logistics

Role-specific conflicts should not reject the project. They should reject or classify only the affected role.

A project with five bad roles and one good role can still pass the project gate.

## Dashboard Workflow

The first implementation slice does not need to fully rebuild the dashboard, but the design target is:

- group by project
- nest roles under projects
- preserve source/scan order
- show bucket counts inside each project
- default role display includes:
  - final bucket
  - career score
  - key reasons
  - required preference questions
  - reviewer downgrade note
  - reviewer impact badge when relevant
- raw first LLM and reviewer output is expandable per role
- model disagreement is visible by default
- reviewer usefulness summary appears for the scan

Reviewer usefulness fields:

- reviewed roles count
- agreed count
- downgraded count
- invalid/unsupported downgrade count
- final bucket changed count

Per-role reviewer display should show:

- first LLM suggested bucket and career score
- reviewer verdict: agree, downgrade, invalid/unsupported
- final bucket
- disagreement badge when they differ
- reviewer evidence for any counted downgrade
- whether the reviewer changed the final bucket

## Preference Learning

When a role lands in `Needs My Preference`, the dashboard and CLI should allow the user to answer:

- allow in future
- reject in future
- only review manually

Answers save reusable profile facts and immediately rescore matching current roles.

Manual correction behavior:

- correcting a role updates that role
- the system suggests a reusable rule
- no rule is silently created
- suggestions can be approved inline from the role
- suggestions also remain available in a central rule-suggestions queue

## Error Handling

- First LLM and reviewer outputs must be schema-validated.
- Invalid output gets one repair retry.
- Failed retry becomes `Data/Parse Error`.
- Reviewer downgrade without exact evidence is ignored for bucket resolution but remains visible in model details.
- Sparse notices are not errors unless the notice makes the missing fact required.

## First Implementation Slice

Implement decision model first:

1. Add bucket enum/constants and structured decision dataclasses.
2. Add first LLM structured output schema and validation.
3. Add reviewer structured validation schema.
4. Add deterministic bucket resolver with tests.
5. Persist structured classifier/reviewer output alongside existing decision rows.
6. Adapt current CLI/dashboard labels enough to expose final bucket and reviewer impact.

Dashboard grouping, preference buttons, CLI preference commands, and full `screening_rules.json` editing can follow after the decision contract is stable.

## Testing Strategy

Add targeted tests for:

- hard reject precedence
- missing preference -> `Needs My Preference`
- known allowed preference -> no reject
- first LLM malformed output -> repair retry -> error
- reviewer downgrade with evidence -> final bucket changes
- reviewer downgrade without evidence -> ignored
- project-wide conflict vs role-specific conflict
- low pay alone does not reject
- low pay + high burden + low career value can reject
- model disagreement visibility fields

Existing parser, project screener, role screener, storage, and UI tests should be updated only where behavior changes.

## Open Implementation Notes

- Keep old decision fields during migration so existing dashboard/history does not break.
- New structured fields can be stored as JSON first to avoid premature schema churn.
- Once stable, add indexed columns only for fields needed by dashboard filtering.
- Keep daily scan defaults and dry-run application safety unchanged.
