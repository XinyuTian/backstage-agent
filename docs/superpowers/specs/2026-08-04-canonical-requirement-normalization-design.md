# Canonical Requirement Normalization Design

Date: 2026-08-04

## Goal

Convert clearly structured casting facts into stable semantic requirements before local matching. The observed `Lead, Male, 18-28` extraction must become separate canonical `gender` and `age_range` requirements while preserving its source evidence.

Candidates must continue through scoring. An explicit mandatory mismatch must remain visible and receive the existing `mandatory_requirement_not_met` cap rather than being filtered out.

## Current Failure

The feature-extraction prompt asks for requirements with evidence but does not define canonical keys or a consistent requirement shape. Dictionary-valued model output bypasses requirement normalization unchanged, and output validation checks only that `requirements` is a dictionary.

Consequently, this valid JSON survives unchanged:

```json
{
  "requirement_1": {
    "requirement": "Male, 18-28",
    "evidence": "Lead, Male, 18-28"
  }
}
```

The matcher-side gender compatibility layer recognizes canonical gender keys, typed gender wrappers, and labels such as `Gender: Male`. It does not recognize the combined untyped label above. The requirement therefore becomes `unknown_needs_user_input`, defaults to non-required, receives partial requirement credit, and avoids the mandatory mismatch cap. Its age information is also unavailable as a semantic field.

## Canonical Requirement Contract

The extraction prompt will request this bounded semantic vocabulary whenever the source states the fact clearly:

- `gender`
- `age_range`
- `ethnicity`
- `union_status`
- `location`
- `language`
- `skills`
- `availability`
- `work_authorization`

Each canonical requirement uses:

```json
{
  "value": "...",
  "required": true,
  "evidence": "verbatim source excerpt",
  "certainty": "explicit"
}
```

Repeated concepts may use stable prefixed keys such as `language_mandarin` or `skill_stage_combat` when a single aggregate value would lose meaning.

The prompt is guidance, not the enforcement boundary. Deterministic normalization and validation must handle recognizable loose model output.

## Certainty And Requiredness

Certainty and requiredness are separate:

- `explicit`: the source directly states the value. It may participate in local matching.
- `inferred`: the value is a reasonable model interpretation but is not directly stated. It is visible in Dashboard Requirements with an `Inferred` label, but contributes no requirement-match points or penalties and cannot trigger a score cap.
- `ambiguous`: the source cannot be safely converted to a canonical fact. It remains a generic requirement with an `Ambiguous` label and follows conservative unknown-requirement behavior.
- `not_specified`: the source does not state a requirement. No requirement is emitted.

Requiredness follows source language:

- Explicit role descriptors and casting attributes are `required: true`.
- Language such as `preferred`, `ideally`, or `a plus` produces `required: false`.
- If mandatory status is unclear, normalization must not promote the requirement to mandatory.

Only a requirement that is both `certainty: explicit` and `required: true` can produce a mandatory mismatch cap.

## Deterministic Normalization

Normalization runs after JSON parsing and before constructing `CandidateFeatures`.

For each requirement:

1. Preserve already canonical entries after filling safe defaults and validating their shape.
2. Inspect generic numbered wrappers for unmistakable semantic facts in their `value`, `requirement`, and `evidence` fields.
3. Split only high-confidence facts. The initial deterministic scope is explicit casting gender and numeric age ranges.
4. Preserve the complete original evidence on every canonical field derived from the same source excerpt.
5. Retain any residual requirement text that was not safely classified; do not silently discard it.
6. Never overwrite a canonical model-provided field with weaker inferred data.

For the regression case, the normalized output is:

```json
{
  "gender": {
    "value": "Male",
    "required": true,
    "evidence": "Lead, Male, 18-28",
    "certainty": "explicit"
  },
  "age_range": {
    "value": "18-28",
    "required": true,
    "evidence": "Lead, Male, 18-28",
    "certainty": "explicit"
  }
}
```

Descriptions such as `young-looking male lead` may yield an explicit gender, but `young-looking` must not be converted into a numeric age range. Unrelated prose such as `natural screen presence` remains generic and conservative.

## Matching And Scoring

The requirement matcher will ignore `inferred` requirements for match credit, penalties, and caps while returning enough structured information for display. Explicit canonical gender continues through the existing profile comparison. An explicit male-only requirement against a female-only profile becomes required `NOT_MET`.

The scorer remains unchanged: it observes the required mismatch and applies the existing `mandatory_requirement_not_met` cap. Candidate generation, persistence, ranking, and Dashboard visibility remain unchanged; no pre-scoring filter is introduced.

Age normalization is included in the feature contract. This change does not invent new age-matching or age-overlap scoring behavior beyond what the current local matcher supports; unsupported canonical facts remain auditable without being guessed.

## Dashboard Presentation

The existing Requirements section will retain canonical semantic labels and evidence. Requirements with `certainty: inferred` will display an `Inferred` marker. Ambiguous generic requirements will display an `Ambiguous` marker when that certainty is present. Explicit requirements need no extra warning label.

The Dashboard presentation must not change stored certainty or scoring behavior.

## Validation And Error Handling

Validation will enforce normalized requirement containers without rejecting the entire extraction for a conservatively retainable loose requirement. It will:

- preserve non-empty evidence;
- normalize recognized `certainty` values;
- avoid treating absent certainty as inferred;
- keep ambiguous content generic;
- reject or conservatively retain malformed structures according to existing loose-output behavior rather than inventing values.

Prompt compliance alone is never considered sufficient validation.

## Tests

Regression coverage will include:

- the exact generic wrapper containing `Male, 18-28` and evidence `Lead, Male, 18-28`;
- canonical `gender` and `age_range` output with requiredness, evidence, and explicit certainty;
- the normalized gender mismatch against a female-only profile;
- application of the existing mandatory mismatch cap without filtering the candidate;
- preservation of unrelated ambiguous numbered requirements;
- refusal to invent a numeric age from qualitative phrases such as `young-looking`;
- inferred requirements remaining visible/displayable while not affecting matching points, penalties, or caps;
- Dashboard `Inferred` and `Ambiguous` markers.

Targeted extractor, matcher, scoring, and Dashboard tests will run first, followed by the full suite because the behavior crosses those module boundaries.

## Documentation

`PROJECT_STATE.md` will describe canonical requirement normalization and certainty-aware scoring as current capabilities. `CHANGELOG.md` will record the corrected user-visible behavior. `ARCHITECTURE.md` does not require an update because module ownership and system flow remain unchanged.

## Non-Goals

- Filtering candidates before scoring.
- Adding a new gender-specific or age-specific score cap.
- Guessing numeric ages, ethnicity, skills, or availability from vague prose.
- Treating inferred facts as confirmed profile mismatches.
- Automatically rewriting historical candidate rows or rescoring August 4 data without separate authorization.
