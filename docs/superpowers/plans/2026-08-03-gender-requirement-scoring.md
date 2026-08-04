# Gender Requirement Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make explicitly male-only roles score as mandatory requirement mismatches against the existing female-only actor profile while keeping every candidate visible.

**Architecture:** Extend the existing local requirement matcher to recognize canonical and numbered-wrapper gender requirements, normalize their casting-gender values, and compare them with `ActorProfile.genders`. Return existing `RequirementMatch` statuses so `score_candidate()` applies `mandatory_requirement_not_met` without a pre-filter, new profile field, or new cap.

**Tech Stack:** Python 3, pytest, existing candidate dataclasses/enums, JSON scoring configuration.

## Global Constraints

- Do not filter candidates before scoring.
- Use `profile.genders`; add no profile field.
- Use the existing `mandatory_requirement_not_met` cap, currently 15.
- Female, any-gender, and unspecified-gender roles must not mismatch a female-only profile.
- Preserve unrelated unknown-requirement behavior.

---

### Task 1: Canonical Gender Requirement Matching

**Files:**
- Modify: `tests/test_requirement_matcher.py`
- Modify: `tests/test_candidate_scoring.py`
- Modify: `src/backstage_agent/requirement_matcher.py`

**Interfaces:**
- Consumes: `match_requirements(features: CandidateFeatures, profile: ActorProfile, rules: dict) -> list[RequirementMatch]` and `ActorProfile.genders`.
- Produces: canonical `gender` matches with `required=True` and an existing `RequirementStatus`.

- [ ] **Step 1: Write failing regressions for the two observed extraction shapes**

```python
def test_numbered_gender_requirement_mismatches_female_profile(actor_profile_factory):
    features = _features({"requirement_1": {
        "requirement": "Gender: Male",
        "evidence": "Kenny - Supporting, Male, 20-40",
    }})
    matches = match_requirements(
        features, actor_profile_factory(genders=["female"]), _rules()
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.NOT_MET
    assert matches[0].required is True
    assert matches[0].local_value == "female"


def test_canonical_gender_requirement_mismatches_female_profile(actor_profile_factory):
    matches = match_requirements(
        _features({"gender": "Male"}),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.NOT_MET
    assert matches[0].required is True
```

Also import `match_requirements` in `tests/test_candidate_scoring.py` and add:

```python
def test_required_gender_mismatch_uses_existing_mandatory_cap(actor_profile_factory):
    features = _features(requirements={"gender": "Male"})
    rules = _rules()
    matches = match_requirements(
        features, actor_profile_factory(genders=["female"]), rules
    )
    score = score_candidate(features, matches, rules)
    assert score.overall_score == 15
    assert score.score_caps == ["mandatory_requirement_not_met"]
    assert "gender requirement not met" in score.negative_drivers
```

- [ ] **Step 2: Run them and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_requirement_matcher.py -k "numbered_gender or canonical_gender" tests/test_candidate_scoring.py::test_required_gender_mismatch_uses_existing_mandatory_cap -v
```

Expected: failures show `UNKNOWN_NEEDS_USER_INPUT`; the numbered shape also retains `requirement_1` and `required=False`, and the integration score has no mandatory cap.

- [ ] **Step 3: Add compatibility tests**

```python
def test_female_gender_requirement_matches_female_profile(actor_profile_factory):
    matches = match_requirements(
        _features({"gender": "Female"}),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    assert matches[0].status is RequirementStatus.MET


def test_any_gender_requirement_matches_female_profile(actor_profile_factory):
    features = _features({"requirement_1": {
        "type": "gender", "value": "Any gender", "evidence": "Open to any gender."
    }})
    matches = match_requirements(
        features, actor_profile_factory(genders=["female"]), _rules()
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.MET


def test_unrelated_numbered_requirement_remains_unknown(actor_profile_factory):
    features = _features({"requirement_1": {
        "requirement": "Natural screen presence",
        "evidence": "Natural, authentic screen presence.",
    }})
    matches = match_requirements(features, actor_profile_factory(), _rules())
    assert matches[0].requirement_key == "requirement_1"
    assert matches[0].status is RequirementStatus.UNKNOWN_NEEDS_USER_INPUT
```

Retain `test_not_specified_placeholder_wrappers_are_ignored` as the unspecified-gender regression.

- [ ] **Step 4: Implement semantic recognition and gender comparison**

Add `import re` and these focused helpers to `requirement_matcher.py`:

```python
_ANY_GENDER_VALUES = {"all genders", "any gender", "any genders",
                      "open to all genders", "open to any gender"}


def _semantic_requirement_key(key: str, requirement: dict) -> str:
    if key.strip().lower() == "gender":
        return "gender"
    if str(requirement.get("type") or "").strip().lower() == "gender":
        return "gender"
    label = str(requirement.get("requirement") or "").strip().lower()
    return "gender" if re.match(r"^gender\s*:", label) else key


def _gender_requirement_text(requirement: dict) -> str:
    for field in ("value", "requirement", "evidence"):
        value = str(requirement.get(field) or "").strip()
        if value:
            return value
    return ""


def _normalize_gender_values(value: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    if normalized in _ANY_GENDER_VALUES:
        return {"any"}
    if normalized.startswith("gender:"):
        normalized = normalized.split(":", 1)[1].strip()
    values = set()
    if re.search(r"\bfemale\b|\bwoman\b|\bwomen\b", normalized):
        values.add("female")
    without_female = re.sub(r"\bfemale\b", "", normalized)
    if re.search(r"\bmale\b|\bman\b|\bmen\b", without_female):
        values.add("male")
    if re.search(r"\bnon[- ]?binary\b", normalized):
        values.add("nonbinary")
    return values


def _evaluate_gender_requirement(profile, requirement):
    local = {value for gender in profile.genders
             for value in _normalize_gender_values(str(gender))}
    local_text = ", ".join(str(gender) for gender in profile.genders)
    required = _normalize_gender_values(_gender_requirement_text(requirement))
    if "any" in required:
        return RequirementStatus.MET, local_text
    if not required or not local:
        return RequirementStatus.UNKNOWN_NEEDS_USER_INPUT, local_text
    status = RequirementStatus.MET if required & local else RequirementStatus.NOT_MET
    return status, local_text
```

Inside `match_requirements`, compute `semantic_key` after `_requirement_dict`. If it is `gender`, call `_evaluate_gender_requirement`, append a `RequirementMatch` with `requirement_key="gender"`, `required=True`, existing `_reason_for_status`, and evidence from the wrapper or normalized gender text, then continue. Use `semantic_key` for configured-rule lookup; leave all other unknown behavior unchanged.

- [ ] **Step 5: Run matcher tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_requirement_matcher.py tests/test_candidate_scoring.py -v`

Expected: all tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add tests/test_requirement_matcher.py tests/test_candidate_scoring.py src/backstage_agent/requirement_matcher.py
git commit -m "fix: match casting gender requirements"
```

---

### Task 2: Existing Score-Cap Integration and Documentation

**Files:**
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Task 1's verified gender-aware scoring behavior.
- Produces: current documentation of the user-visible correction.

- [ ] **Step 1: Update documentation**

Add to `PROJECT_STATE.md` Current Capabilities:

```markdown
- Candidate requirement matching recognizes canonical and numbered-wrapper casting-gender requirements, compares them with existing profile genders, and applies the normal mandatory-mismatch cap without hiding candidates.
```

Add under `CHANGELOG.md` Unreleased / Fixed:

```markdown
- Fixed incompatible casting-gender requirements so canonical and numbered extraction shapes use stored profile genders and receive the existing mandatory-mismatch cap instead of unknown-requirement partial credit.
```

- [ ] **Step 2: Run targeted verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_requirement_matcher.py tests/test_candidate_scoring.py -v
```

Expected: all selected tests pass.

- [ ] **Step 3: Run full verification**

Run `.venv/bin/python -m pytest`, then `git diff --check`, then `git status --short`.

Expected: full suite passes; no whitespace errors; only planned changes appear alongside pre-existing `.gitignore` and `.worktrees/` changes.

- [ ] **Step 4: Commit Task 2**

```bash
git add PROJECT_STATE.md CHANGELOG.md
git commit -m "test: cover gender mismatch score cap"
```

## Operational Verification

Do not overwrite August 3 candidate rows in this implementation. A deliberate exact-date overwrite rescore can rebuild stored scores later, but that database mutation requires separate authorization.
