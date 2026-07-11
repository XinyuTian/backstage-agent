# Travel, Host Confidence, And Identity Policy Design

Date: 2026-07-11

## Purpose

Today's scan exposed two decision-quality problems that should not become one-off patches:

- A Sacramento project was rejected as too far even though it was only a one-day shoot, which may be workable.
- A host role looked acceptable to the system, but the actor is not confident as a host or entertainer.
- A vacuum commercial built around a French family should reject when the actor does not match the required identity/look.

The fix should be a moderate refactor that extends the existing decision core with reusable policy concepts. It should preserve the current project-first, role-second pipeline and the local rule -> first LLM -> downgrade-only reviewer structure.

## Goals

- Replace hard distance rejection with a travel tradeoff policy.
- Model host/presenter roles by confidence subtype rather than one broad role type.
- Treat clear identity, appearance, nationality, culture, and family/look mismatches as objective rejects.
- Keep these rules auditable in structured artifacts and dashboard explanations.
- Prefer reusable `screening_rules.json` policy over scattered prompt or local-rule patches.
- Keep `Needs My Preference` sparse; do not ask the actor every time policy can resolve the case.

## Non-Goals

- Do not implement a correction-feedback UI in this slice.
- Do not redesign the full dashboard.
- Do not add live Backstage submission.
- Do not replace the existing decision core or reviewer.
- Do not infer private identity details beyond what the profile explicitly says.

## Policy Summary

### Travel Tradeoff

Distance is not a hard reject by itself. Travel burden is resolved from:

- distance
- shoot days
- role value
- pay rate
- known support such as travel reimbursement or lodging

Pay is the least important factor, but it can upgrade a role when logistics are easy.

Default behavior:

- Far distance + one shooting day + strong role value can pass or go to `Ready For Review`.
- Far distance + one shooting day + okay role value + good pay can pass or go to `Ready For Review`.
- Far distance + unknown shoot days goes to `Ready For Review`.
- Far distance + multiple days + weak role value, poor pay, or no support usually rejects.
- Far distance + multiple days + strong role value and meaningful support goes to `Ready For Review`.
- Good pay can upgrade a low-value or low-confidence role when logistics are easy, including to `Auto Apply/Draft` for simple local or one-day cases.

Travel should not usually produce `Needs My Preference`. If logistics are unclear but not obviously bad, use `Ready For Review`.

### Host Confidence

Host/presenter work is subtype-sensitive.

Default behavior:

- Pure live host, emcee, hype-person, entertainer, event personality, or "keep the crowd engaged" roles reject.
- Scripted presenter, spokesperson, interviewer, product presenter, or unclear host style goes to `Ready For Review`.
- Acting-adjacent host roles can pass when there is a script, character, scene, or clear performance frame and the rest of the opportunity is strong.
- Ambiguous host subtype goes to `Ready For Review`, not `Reject`.
- Only genuinely new reusable host-style preferences should become `Needs My Preference`.

The system should not treat the label "Host" as enough evidence for automatic approval.

### Identity And Appearance Mismatch

Clear identity, appearance, nationality, cultural, native-language, or family/look requirements are objective matching constraints.

Default behavior:

- Reject at project level when the whole project concept requires a mismatch.
- Reject at role level when only a specific role requires a mismatch.
- "French family", "French look", "authentic French family", and similar family/look concepts reject when the actor profile does not match.
- If the requirement is only French-language dialogue and not identity/look, use language ability instead of appearance.
- If evidence is unclear, use `Ready For Review` rather than `Needs My Preference`.

This policy applies at both project and role levels depending on notice evidence.

## Decision Inputs

The first LLM structured output should add or consistently populate these policy fields:

- `travel_burden`: controlled value such as `local`, `day_trip`, `high_burden`, or `unknown`
- `shoot_day_count`: integer when known, otherwise null
- `travel_support`: controlled value such as `none`, `reimbursed`, `lodging`, `unknown`
- `role_confidence`: controlled value such as `high`, `medium`, `low`, or `unknown`
- `host_subtype`: controlled value such as `pure_live_host`, `scripted_presenter`, `interviewer`, `acting_adjacent_host`, `ambiguous_host`, or `not_host`
- `identity_requirement`: structured evidence for required identity/look/language/family concepts

Existing fields remain useful:

- `role_type`
- `project_type`
- `career_value_score`
- `pay_burden`
- `travel_burden`
- `time_burden`
- `fit_reasons`
- `concerns`
- `evidence_snippets`

## Resolver Rules

The deterministic resolver should use these policies after schema validation and hard local rejects.

Priority:

1. Data/model/schema failure after retry -> `Data/Parse Error`
2. Clear identity/appearance mismatch -> `Reject`
3. Pure live host/emcee/entertainer -> `Reject`
4. Host ambiguity or scripted/presenter host -> `Ready For Review`
5. Travel tradeoff policy -> `Auto Apply/Draft`, `Ready For Review`, or `Reject`
6. Existing career-value and preference policy -> final bucket
7. Reviewer can only downgrade according to existing reviewer policy

Travel policy should not override objective hard rejects.

Pay can upgrade only when logistics are easy enough. It should not override a clear identity mismatch or pure-entertainer host rejection.

## Rules File Shape

Add explicit sections to `screening_rules.json` rather than hardcoding every case.

Suggested sections:

```json
{
  "travel_policy": {
    "distance_factors": ["distance", "shoot_day_count", "career_value_score", "pay_burden", "travel_support"],
    "unknown_far_days_bucket": "ready_for_review",
    "pay_can_upgrade_easy_logistics": true
  },
  "role_confidence": {
    "host_presenter": {
      "pure_live_host": "reject",
      "scripted_presenter": "ready_for_review",
      "interviewer": "ready_for_review",
      "acting_adjacent_host": "policy_resolve",
      "ambiguous_host": "ready_for_review"
    }
  },
  "identity_policy": {
    "clear_project_concept_mismatch": "reject",
    "clear_role_requirement_mismatch": "reject",
    "unclear_identity_evidence": "ready_for_review"
  }
}
```

The implementation can refine names, but the meaning should stay stable.

## Prompt And Reviewer Behavior

First-pass LLM:

- Classify travel burden using distance, shoot days, support, role value, and pay.
- Classify host subtype instead of treating all host roles as equal.
- Identify identity/look/language/family requirements with exact evidence snippets.
- Avoid rejecting far one-day shoots solely for distance.
- Avoid approving pure host/emcee/entertainer roles as acting fits.

Reviewer:

- Verify that travel, host subtype, and identity evidence are supported by notice text.
- Downgrade unsupported `Auto Apply/Draft` outcomes to `Ready For Review`.
- Reject only with exact evidence for objective mismatch or pure-entertainer host work.
- Do not downgrade based on vague discomfort without evidence.

## Dashboard Expectations

The dashboard should make these policy reasons legible:

- show final bucket
- show travel burden and shoot days when known
- show host subtype when relevant
- show identity/appearance mismatch evidence when it caused rejection
- show reviewer impact if the reviewer changed a travel/host/identity outcome

No major dashboard redesign is required for this slice.

## Testing Strategy

Add focused tests for:

- Sacramento or similar far-ish one-day acting role is not rejected solely for distance.
- Far project with unknown days becomes `Ready For Review`.
- Far multi-day weak/unsupported role rejects.
- Pure live host/emcee rejects.
- Scripted presenter or ambiguous host becomes `Ready For Review`.
- Acting-adjacent host can pass when role value and logistics are strong.
- French-family/French-look commercial rejects at project level when the whole concept requires it.
- Identity mismatch rejects at role level when only the role requires it.
- French-language-only requirement uses language ability rather than appearance.

Run the full test suite after implementation because this touches decision core, project screener, role screener, reviewer, storage/dashboard explanations, and CLI summaries.
