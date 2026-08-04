# Gender Requirement Scoring Design

Date: 2026-08-03

## Goal

Explicitly male-only roles must remain visible in the candidate scoring workflow but receive the existing mandatory-requirement-mismatch cap when the actor profile lists only female casting genders. Female, any-gender, and unspecified-gender roles must remain unaffected.

## Current Failure

Gender evidence reaches candidate feature extraction in inconsistent shapes. One role may contain a canonical `gender` requirement, while another may contain a numbered wrapper such as `requirement_1` whose value says `Gender: Male`. The requirement matcher currently dispatches only by the outer dictionary key and has no built-in gender evaluator. Both shapes therefore become unknown requirements, receive partial credit, and avoid the existing mandatory-mismatch cap.

## Design

Gender matching will be part of the existing requirement-matching and scoring flow. There will be no pre-scoring filter, new profile field, or gender-specific score cap.

The matcher will recognize gender requirements from both canonical keys and structured numbered wrappers. It will normalize explicit casting-gender values before comparing them with the existing `ActorProfile.genders` list. An explicitly male-only requirement compared with a female-only profile will produce a required `NOT_MET` requirement match.

The existing scorer will then apply `mandatory_requirement_not_met`, currently capped at 15. The candidate remains stored, ranked, and visible with an auditable mismatch reason.

Any-gender requirements will match all profile casting genders. Unspecified or genuinely ambiguous gender evidence will not be converted into a mismatch. Existing behavior for unrelated unknown requirements will remain unchanged.

## Data Flow

1. Feature extraction returns candidate requirements and source evidence.
2. Requirement matching identifies the semantic requirement type, including numbered wrappers.
3. Gender values are normalized and compared with `profile.genders`.
4. A required incompatible gender becomes `NOT_MET`.
5. Existing deterministic scoring applies `mandatory_requirement_not_met` and caps the score.
6. Storage and the candidate dashboard continue to show the candidate and its score trace.

## Tests

Regression tests will cover:

- Kenny's numbered-wrapper shape containing `Gender: Male`.
- Masked Man's canonical `gender: Male` shape.
- Female requirements matching a female-only profile.
- Any-gender requirements matching without a cap.
- Unspecified gender remaining non-mismatching.
- The existing scorer capping an explicit required gender mismatch at 15.

Targeted requirement-matcher and candidate-scoring tests will run first, followed by the full test suite because the change crosses extraction normalization, matching, and scoring behavior.

## Documentation

`PROJECT_STATE.md` will record deterministic casting-gender matching as a current capability. `CHANGELOG.md` will record the user-visible correction. No architecture document change is needed because module boundaries and system flow remain the same.
