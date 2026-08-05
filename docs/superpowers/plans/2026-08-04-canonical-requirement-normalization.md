# Canonical Requirement Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize explicit gender and numeric age facts from loose numbered requirements into canonical fields, make inferred requirements score-neutral, and label uncertainty in the candidate Dashboard.

**Architecture:** Extend `feature_extractor.py` as the enforcement boundary after LLM JSON parsing: prompt for a bounded canonical vocabulary, normalize every requirement container, and split only unmistakable gender and numeric age facts. Keep scoring local by teaching `requirement_matcher.py` to return `NOT_APPLICABLE` score-neutral matches for inferred requirements. Preserve the existing scorer and mandatory cap, and expose certainty through the existing requirement-flattening/rendering path in `ui.py`.

**Tech Stack:** Python 3, pytest, existing dataclasses/enums, stdlib `re`, server-rendered HTML.

## Global Constraints

- Do not filter candidates before scoring.
- Only `certainty: explicit` plus `required: true` may trigger a mandatory mismatch cap.
- `inferred` requirements remain visible but receive no points, penalties, negative drivers, or caps.
- Preserve the complete original evidence for each derived canonical fact.
- Normalize only high-confidence casting gender and numeric age ranges in deterministic code.
- Keep ambiguous requirements generic; do not invent age, ethnicity, skills, or availability.
- Do not overwrite or rescore stored August 4 candidate rows without separate authorization.
- Preserve unrelated working-tree changes.

---

### Task 1: Canonical Feature-Extraction Contract And Normalization

**Files:**
- Modify: `tests/test_feature_extractor.py`
- Modify: `src/backstage_agent/feature_extractor.py`

**Interfaces:**
- Consumes: `_remove_score_fields(data: dict) -> tuple[dict, bool]` and `_normalize_requirements(value: object) -> dict`.
- Produces: normalized `CandidateFeatures.requirements` entries with `value`, `required`, `evidence`, and `certainty` fields.

- [ ] **Step 1: Add a failing exact regression for `Lead, Male, 18-28`**

Add a feature-extractor test using the existing fake client pattern:

```python
def test_feature_extractor_splits_explicit_gender_and_age_from_numbered_requirement(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
    payload = {
        "role_type": "commercial",
        "project_type": "commercial",
        "requirements": {
            "requirement_1": {
                "requirement": "Male, 18-28",
                "evidence": "Lead, Male, 18-28",
            }
        },
        "project_signals": {},
        "compensation": {},
        "uncertainty": {},
        "evidence_snippets": ["Lead, Male, 18-28"],
    }
    extractor = FeatureExtractor(settings_factory(), actor_profile_factory())
    extractor._client = fake_chat_client_factory([payload])
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="commercial",
        role_key="male-lead",
        title="Commercial, San Francisco — Male Lead",
        notice=casting_notice_factory(),
    )

    features = extractor.extract(candidate)

    assert features.requirements == {
        "gender": {
            "value": "Male",
            "required": True,
            "evidence": "Lead, Male, 18-28",
            "certainty": "explicit",
        },
        "age_range": {
            "value": "18-28",
            "required": True,
            "evidence": "Lead, Male, 18-28",
            "certainty": "explicit",
        },
    }
```

- [ ] **Step 2: Run the exact test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_feature_extractor.py::test_feature_extractor_splits_explicit_gender_and_age_from_numbered_requirement -v
```

Expected: FAIL because `requirements` still contains unchanged `requirement_1`.

- [ ] **Step 3: Add conservative normalization regressions**

Import `_normalize_requirements` and add direct normalization tests:

```python
def test_normalize_requirements_does_not_invent_numeric_age_from_qualitative_text():
    requirements = _normalize_requirements({
        "requirement_1": {
            "requirement": "Young-looking male lead",
            "evidence": "Young-looking male lead",
        }
    })
    assert requirements["gender"] == {
        "value": "Male",
        "required": True,
        "evidence": "Young-looking male lead",
        "certainty": "explicit",
    }
    assert "age_range" not in requirements
    assert requirements["requirement_1"]["requirement"] == "Young-looking"
    assert requirements["requirement_1"]["certainty"] == "ambiguous"


def test_normalize_requirements_preserves_unrelated_ambiguous_requirement():
    requirements = _normalize_requirements({
        "requirement_1": {
            "requirement": "Natural screen presence",
            "evidence": "Natural, authentic screen presence.",
        }
    })
    assert requirements == {
        "requirement_1": {
            "requirement": "Natural screen presence",
            "evidence": "Natural, authentic screen presence.",
            "required": False,
            "certainty": "ambiguous",
        }
    }
```

Use shared private test helpers only if they reduce repeated candidate/payload setup without obscuring assertions.

- [ ] **Step 4: Run the conservative tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_feature_extractor.py -k "qualitative_text or ambiguous_requirement" -v
```

Expected: FAIL because dictionary requirements bypass semantic normalization.

- [ ] **Step 5: Implement the minimal deterministic normalizer**

In `feature_extractor.py`:

1. Make `_normalize_requirements()` convert both dictionaries and lists into a common dictionary and then normalize each entry.
2. Add focused regex helpers:

```python
_NUMBERED_REQUIREMENT_RE = re.compile(r"^requirement_\d+$")
_AGE_RANGE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–—]\s*(\d{1,2})(?!\d)")
_GENDER_PATTERNS = (
    ("Nonbinary", re.compile(r"\bnon[- ]?binary\b", re.IGNORECASE)),
    ("Female", re.compile(r"\b(?:female|woman|women)\b", re.IGNORECASE)),
    ("Male", re.compile(r"\b(?:male|man|men)\b", re.IGNORECASE)),
)
_CERTAINTIES = {"explicit", "inferred", "ambiguous"}
```

3. Normalize wrappers through focused helpers named `_normalize_requirement_map`, `_normalize_requirement_entry`, `_split_numbered_requirement`, `_requirement_text`, and `_requirement_evidence`. The first and third return semantic requirement maps; the others return one normalized entry or one source string.

4. For a numbered wrapper, search combined substantive text from `value` and `requirement`, falling back to evidence only when those fields are absent. Emit canonical gender and age fields only when their regex matches.
5. Use the original non-empty evidence for every derived field. Default unmistakable role descriptors to `required=True` and `certainty="explicit"`.
6. Remove only recognized tokens and neutral separators from residual text. If substantive residual text remains, retain the numbered wrapper with `certainty="ambiguous"` and conservative `required=False` unless the model explicitly supplied requiredness.
7. Preserve canonical model fields. Normalize missing certainty to `explicit` only for canonical fields with a non-empty direct value; preserve recognized model certainty values.
8. If multiple wrappers produce the same canonical key, preserve the first explicit entry instead of silently overwriting it.

- [ ] **Step 6: Strengthen the extraction prompt**

Replace the short requirements sentence in `_FEATURE_EXTRACTION_PROMPT` with a compact explicit contract that:

```text
Uses canonical keys gender, age_range, ethnicity, union_status, location,
language, skills, availability, and work_authorization when directly stated.
Each requirement contains value, required, evidence, and certainty, where
certainty is explicit, inferred, or ambiguous. Use required=false for preferred,
ideally, or a-plus language. Never convert qualitative age language to a numeric
range. Keep unclear requirements generic rather than guessing.
```

Keep the existing ban on scoring/ranking/apply decisions.

- [ ] **Step 7: Run extractor tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_feature_extractor.py -v
```

Expected: all extractor tests PASS, including existing list and loose-container compatibility tests.

- [ ] **Step 8: Commit Task 1**

```bash
git add tests/test_feature_extractor.py src/backstage_agent/feature_extractor.py
git commit -m "fix: normalize canonical casting requirements"
```

---

### Task 2: Certainty-Aware Matching And Existing Score Cap

**Files:**
- Modify: `tests/test_requirement_matcher.py`
- Modify: `tests/test_candidate_scoring.py`
- Modify: `src/backstage_agent/requirement_matcher.py`
- Modify: `src/backstage_agent/scoring.py`

**Interfaces:**
- Consumes: normalized requirement dictionaries from Task 1.
- Produces: `RequirementMatch` values where inferred requirements use `RequirementStatus.NOT_APPLICABLE`, `required=False`, and `score_impact=0`; explicit gender mismatch remains required `NOT_MET`.

- [ ] **Step 1: Add failing matcher tests for inferred neutrality and the exact normalized gender**

Add:

```python
def test_inferred_requirement_is_visible_but_not_applicable(actor_profile_factory):
    matches = match_requirements(
        _features({
            "gender": {
                "value": "Male",
                "required": True,
                "evidence": "Masculine presentation preferred.",
                "certainty": "inferred",
            }
        }),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.NOT_APPLICABLE
    assert matches[0].required is False
    assert matches[0].score_impact == 0


def test_explicit_canonical_gender_from_combined_evidence_mismatches(actor_profile_factory):
    matches = match_requirements(
        _features({
            "gender": {
                "value": "Male",
                "required": True,
                "evidence": "Lead, Male, 18-28",
                "certainty": "explicit",
            },
            "age_range": {
                "value": "18-28",
                "required": True,
                "evidence": "Lead, Male, 18-28",
                "certainty": "explicit",
            },
        }),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    gender = next(match for match in matches if match.requirement_key == "gender")
    assert gender.status is RequirementStatus.NOT_MET
    assert gender.required is True
```

- [ ] **Step 2: Add a failing scorer regression proving no inferred score effect**

In `tests/test_candidate_scoring.py`, compare an inferred match with no requirements:

```python
def test_inferred_requirement_does_not_change_requirement_score_or_caps():
    rules = _rules()
    features = _features(requirements={
        "gender": {
            "value": "Male",
            "required": True,
            "evidence": "Masculine presentation preferred.",
            "certainty": "inferred",
        }
    })
    matches = [RequirementMatch(
        requirement_key="gender",
        status=RequirementStatus.NOT_APPLICABLE,
        required=False,
        local_value="",
        evidence="Masculine presentation preferred.",
        reason="Inferred requirement is shown for review but not scored.",
        score_impact=0,
    )]
    inferred_score = score_candidate(features, matches, rules)
    baseline_score = score_candidate(_features(requirements={}), [], rules)
    assert inferred_score.subscores["their_requirements_match"] == baseline_score.subscores["their_requirements_match"]
    assert inferred_score.score_caps == baseline_score.score_caps
    assert "gender requirement met" not in inferred_score.positive_drivers
    assert "gender needs user input" not in inferred_score.negative_drivers
```

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_requirement_matcher.py -k "inferred_requirement or combined_evidence" tests/test_candidate_scoring.py::test_inferred_requirement_does_not_change_requirement_score_or_caps -v
```

Expected: inferred gender is currently evaluated as a required mismatch and/or changes the optional requirement allocation.

- [ ] **Step 4: Implement inferred requirement neutrality**

In `match_requirements()`, immediately after `_requirement_dict()`:

```python
certainty = str(requirement.get("certainty") or "explicit").strip().lower()
if certainty == "inferred":
    matches.append(
        RequirementMatch(
            requirement_key=_semantic_requirement_key(key, requirement),
            status=RequirementStatus.NOT_APPLICABLE,
            required=False,
            local_value="",
            evidence=str(requirement.get("evidence") or ""),
            reason="Inferred requirement is shown for review but not scored.",
            score_impact=0,
        )
    )
    continue
```

In `scoring.py`, make the score-neutral contract explicit by filtering `NOT_APPLICABLE` matches before requirement allocation:

```python
scored_matches = [
    match for match in matches
    if match.status is not RequirementStatus.NOT_APPLICABLE
]
```

Use `scored_matches` throughout `_requirement_breakdown()`. Leave driver and cap functions unchanged because they already ignore `NOT_APPLICABLE`.

For gender matches, preserve `required=bool(requirement.get("required", True))` rather than forcing every explicit gender to mandatory. This keeps `preferred` gender requirements optional while the regression case remains mandatory.

- [ ] **Step 5: Verify the existing mandatory cap end to end**

Extend `test_required_gender_mismatch_uses_existing_mandatory_cap` or add a separate case using the exact normalized entries. Assert:

```python
assert score.overall_score == 15
assert score.score_caps == ["mandatory_requirement_not_met"]
assert "gender requirement not met" in score.negative_drivers
```

- [ ] **Step 6: Run matcher and scoring tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_requirement_matcher.py tests/test_candidate_scoring.py -v
```

Expected: all selected tests PASS, including unrelated unknown requirements and any-gender compatibility.

- [ ] **Step 7: Commit Task 2**

```bash
git add tests/test_requirement_matcher.py tests/test_candidate_scoring.py src/backstage_agent/requirement_matcher.py src/backstage_agent/scoring.py
git commit -m "fix: keep inferred requirements score neutral"
```

---

### Task 3: Dashboard Certainty Labels And Documentation

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py`
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: requirement dictionaries containing `certainty` from Task 1.
- Produces: flattened requirement items whose `importance` metadata includes `Inferred` or `Ambiguous`, rendered by `_render_evidence_list(items, include_metadata=True)`.

- [ ] **Step 1: Add failing Dashboard flattening and rendering tests**

Add:

```python
def test_flatten_requirements_labels_inferred_and_ambiguous_certainty():
    requirements = {
        "gender": {
            "value": "Male",
            "required": False,
            "evidence": "Masculine presentation preferred.",
            "certainty": "inferred",
        },
        "requirement_1": {
            "requirement": "Young-looking",
            "required": False,
            "evidence": "Young-looking male lead",
            "certainty": "ambiguous",
        },
    }

    flattened = _flatten_requirements(requirements)

    assert flattened == [
        {
            "description": "Gender",
            "importance": "inferred",
            "evidence": "Masculine presentation preferred.",
        },
        {
            "description": "Young-looking",
            "importance": "ambiguous",
            "evidence": "Young-looking male lead",
        },
    ]
```

Add a `_render_readable_evidence()` assertion using a minimal view with those feature requirements:

```python
html = _render_readable_evidence(view)
assert "Inferred" in html
assert "Ambiguous" in html
assert "Masculine presentation preferred." in html
```

- [ ] **Step 2: Run the Dashboard tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "certainty or inferred_and_ambiguous" -v
```

Expected: FAIL because `_flatten_requirements()` ignores `value`, `requirement`, and `certainty` in structured canonical entries.

- [ ] **Step 3: Implement certainty-aware flattening**

Inside the dictionary branch of `_flatten_requirements()`:

```python
description = _clean_text(
    item.get("description")
    or item.get("requirement")
)
value = _clean_text(item.get("value"))
certainty = _clean_text(item.get("certainty")).lower()
importance = _clean_text(item.get("importance"))
if certainty in {"inferred", "ambiguous"}:
    importance = certainty
```

For canonical semantic keys, use `_humanize(semantic_key)` as the description and show the direct `value` as evidence only when source evidence is absent. For numbered wrappers, prefer `requirement`/`description`. Continue suppressing duplicate evidence and technical fields.

No new CSS is needed: `_render_evidence_list(items, include_metadata=True)` already humanizes `importance`, yielding `Inferred` and `Ambiguous` text.

- [ ] **Step 4: Run the complete candidate UI tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -v
```

Expected: all candidate UI tests PASS, including prior readable-evidence and scalar-map behavior.

- [ ] **Step 5: Update current-state documentation**

In `PROJECT_STATE.md`, replace the narrow gender-wrapper capability with a concise current statement that explicit gender and age facts are canonically normalized, inferred requirements are visible but score-neutral, and explicit gender mismatches use the existing cap without hiding candidates.

In `CHANGELOG.md` under `Unreleased / Fixed`, add:

```markdown
- Canonicalized explicit gender and numeric age facts from loose numbered candidate requirements, kept inferred requirements visible but score-neutral, and preserved the existing mandatory-mismatch cap without filtering candidates.
```

- [ ] **Step 6: Run targeted cross-module verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_feature_extractor.py tests/test_requirement_matcher.py tests/test_candidate_scoring.py tests/test_ui_candidates.py -v
```

Expected: all targeted tests PASS.

- [ ] **Step 7: Run full verification**

Run:

```bash
.venv/bin/python -m pytest
git diff --check
git status --short
```

Expected: the full suite exits 0; `git diff --check` prints nothing; status contains only planned task files plus the pre-existing unrelated modification to `docs/superpowers/specs/2026-08-04-bootstrap-calibration-lifecycle-design.md`.

- [ ] **Step 8: Commit Task 3**

```bash
git add tests/test_ui_candidates.py src/backstage_agent/ui.py PROJECT_STATE.md CHANGELOG.md
git commit -m "fix: show requirement certainty in candidates"
```

## Operational Verification

Do not rescore or overwrite August 4 candidate rows as part of implementation. After code verification, report that historical candidate data and the live launchd-managed Dashboard were not refreshed unless the user separately authorizes those state-changing actions.
