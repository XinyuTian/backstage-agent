# Role Selection Decision Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first implementation slice from the approved role-selection design: five final buckets, structured first LLM output, downgrade-only reviewer validation, deterministic bucket resolution, and minimal storage/dashboard exposure.

**Architecture:** Keep the existing project-first, role-second pipeline and current local rule -> first LLM -> reviewer structure. Add a focused decision core module that validates structured model outputs and resolves the final bucket deterministically, then adapt the existing screeners, reviewer, storage, CLI/dashboard labels, and agent orchestration around that contract.

**Tech Stack:** Python 3.13, dataclasses, JSON, SQLite via existing `DecisionStore`, pytest, existing OpenAI-compatible chat clients.

## Global Constraints

- Preserve the current three-filter structure: local rules, first LLM screening, second LLM reviewer.
- Final outcomes are exactly: `Auto Apply/Draft`, `Ready For Review`, `Needs My Preference`, `Reject`, `Data/Parse Error`.
- The pipeline always screens projects before roles; role screening only runs when the project bucket allows role screening.
- Application drafting only considers role-level `Auto Apply/Draft` outcomes.
- Objective hard rejects stay in tested Python code.
- The reviewer is downgrade-only and reviewer disagreement only counts when backed by exact notice evidence.
- Invalid first LLM or reviewer output gets one repair retry; failed retry becomes `Data/Parse Error`.
- Sparse notices are not errors unless the notice makes the missing fact required.
- Keep daily scan defaults and dry-run application safety unchanged.
- Keep existing decision fields during migration so existing dashboard/history does not break.

---

## File Structure

- Create `src/backstage_agent/decision_core.py`
  - Owns bucket constants, structured classifier/reviewer dataclasses, JSON validation, reviewer impact calculation, and deterministic bucket resolution.
- Create `screening_rules.json`
  - Holds initial bucket labels, role-type career value defaults, known preference labels, and reviewer downgrade policy.
- Modify `src/backstage_agent/models.py`
  - Add optional structured fields to `ScreeningDecision` and `ReviewDecision` while preserving existing fields.
- Modify `src/backstage_agent/screener.py`
  - Convert first-pass role LLM output to the structured classifier schema with one repair retry.
- Modify `src/backstage_agent/project_screener.py`
  - Convert first-pass project LLM output to the structured classifier schema with one repair retry.
- Modify `src/backstage_agent/reviewer.py`
  - Convert reviewer output to structured downgrade-only validation with one repair retry.
- Modify `src/backstage_agent/agent.py`
  - Use final buckets to decide project continuation, role review, and application drafting.
- Modify `src/backstage_agent/storage.py`
  - Persist structured classifier/reviewer JSON, final bucket, reviewer impact, and schema errors as JSON/text columns.
- Modify `src/backstage_agent/ui.py`
  - Minimally expose final bucket, model disagreement, reviewer impact, and expandable structured model details.
- Modify `src/backstage_agent/cli.py`
  - Update summary counts to include final buckets while preserving existing summary fields during migration.
- Create/modify tests:
  - `tests/test_decision_core.py`
  - `tests/test_structured_screening.py`
  - `tests/test_structured_reviewer.py`
  - `tests/test_agent_review_gate.py`
  - `tests/test_storage_dashboard.py`
  - `tests/test_ui_labels.py`
  - `tests/test_cli_summary.py`

---

### Task 1: Decision Core Types And Rules Loader

**Files:**
- Create: `src/backstage_agent/decision_core.py`
- Create: `screening_rules.json`
- Modify: `src/backstage_agent/models.py`
- Test: `tests/test_decision_core.py`

**Interfaces:**
- Produces:
  - `DecisionBucket` enum with values `auto_apply_draft`, `ready_for_review`, `needs_my_preference`, `reject`, `data_parse_error`
  - `StructuredScreening.from_json(data: dict) -> StructuredScreening`
  - `StructuredReview.from_json(data: dict) -> StructuredReview`
  - `DecisionArtifacts` dataclass
  - `load_screening_rules(path: Path | str = "screening_rules.json") -> ScreeningRules`
- Consumes:
  - Existing `ScreeningDecision` and `ReviewDecision` are extended with optional `final_bucket`, `classifier_json`, `reviewer_json`, `reviewer_impact`, and `schema_error`.

- [ ] **Step 1: Write failing tests for bucket enum and classifier validation**

Add `tests/test_decision_core.py`:

```python
import pytest

from backstage_agent.decision_core import (
    DecisionBucket,
    StructuredScreening,
    load_screening_rules,
)


def test_decision_bucket_values_are_stable():
    assert DecisionBucket.AUTO_APPLY_DRAFT.value == "auto_apply_draft"
    assert DecisionBucket.READY_FOR_REVIEW.value == "ready_for_review"
    assert DecisionBucket.NEEDS_MY_PREFERENCE.value == "needs_my_preference"
    assert DecisionBucket.REJECT.value == "reject"
    assert DecisionBucket.DATA_PARSE_ERROR.value == "data_parse_error"


def test_structured_screening_validates_required_fields():
    parsed = StructuredScreening.from_json(
        {
            "suggested_bucket": "auto_apply_draft",
            "role_type": "scripted_theater",
            "project_type": "theater",
            "career_value_score": 5,
            "required_preferences": [],
            "missing_preference_keys": [],
            "pay_burden": "low",
            "travel_burden": "low",
            "time_burden": "medium",
            "fit_reasons": ["Named scripted role"],
            "concerns": [],
            "evidence_snippets": ["Lead, Female, 30-50"],
            "confidence": 0.91,
        }
    )

    assert parsed.suggested_bucket is DecisionBucket.AUTO_APPLY_DRAFT
    assert parsed.career_value_score == 5
    assert parsed.evidence_snippets == ["Lead, Female, 30-50"]


def test_structured_screening_rejects_missing_required_field():
    with pytest.raises(ValueError, match="missing required structured screening fields"):
        StructuredScreening.from_json({"suggested_bucket": "auto_apply_draft"})


def test_structured_screening_rejects_out_of_range_career_score():
    data = {
        "suggested_bucket": "auto_apply_draft",
        "role_type": "scripted_theater",
        "project_type": "theater",
        "career_value_score": 6,
        "required_preferences": [],
        "missing_preference_keys": [],
        "pay_burden": "low",
        "travel_burden": "low",
        "time_burden": "low",
        "fit_reasons": [],
        "concerns": [],
        "evidence_snippets": [],
        "confidence": 0.8,
    }

    with pytest.raises(ValueError, match="career_value_score"):
        StructuredScreening.from_json(data)


def test_default_screening_rules_load():
    rules = load_screening_rules()

    assert rules.career_value["scripted_acting"] == 5
    assert rules.preferences["active_instagram_tagging"]["profile_key"] == (
        "comfortable_with_active_instagram_tagging"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_decision_core.py -v
```

Expected: FAIL because `backstage_agent.decision_core` does not exist.

- [ ] **Step 3: Add decision core implementation**

Create `src/backstage_agent/decision_core.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class DecisionBucket(str, Enum):
    AUTO_APPLY_DRAFT = "auto_apply_draft"
    READY_FOR_REVIEW = "ready_for_review"
    NEEDS_MY_PREFERENCE = "needs_my_preference"
    REJECT = "reject"
    DATA_PARSE_ERROR = "data_parse_error"


@dataclass(frozen=True)
class StructuredScreening:
    suggested_bucket: DecisionBucket
    role_type: str
    project_type: str
    career_value_score: int
    required_preferences: list[str]
    missing_preference_keys: list[str]
    pay_burden: str
    travel_burden: str
    time_burden: str
    fit_reasons: list[str]
    concerns: list[str]
    evidence_snippets: list[str]
    confidence: float
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StructuredScreening":
        required = {
            "suggested_bucket",
            "role_type",
            "project_type",
            "career_value_score",
            "required_preferences",
            "missing_preference_keys",
            "pay_burden",
            "travel_burden",
            "time_burden",
            "fit_reasons",
            "concerns",
            "evidence_snippets",
            "confidence",
        }
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(f"missing required structured screening fields: {', '.join(missing)}")
        score = int(data["career_value_score"])
        if score < 0 or score > 5:
            raise ValueError("career_value_score must be between 0 and 5")
        confidence = float(data["confidence"])
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be between 0 and 1")
        return cls(
            suggested_bucket=DecisionBucket(str(data["suggested_bucket"])),
            role_type=str(data["role_type"]),
            project_type=str(data["project_type"]),
            career_value_score=score,
            required_preferences=[str(value) for value in data["required_preferences"]],
            missing_preference_keys=[str(value) for value in data["missing_preference_keys"]],
            pay_burden=str(data["pay_burden"]),
            travel_burden=str(data["travel_burden"]),
            time_burden=str(data["time_burden"]),
            fit_reasons=[str(value) for value in data["fit_reasons"]],
            concerns=[str(value) for value in data["concerns"]],
            evidence_snippets=[str(value) for value in data["evidence_snippets"]],
            confidence=confidence,
            raw=dict(data),
        )


@dataclass(frozen=True)
class StructuredReview:
    verdict: str
    downgrade_to: DecisionBucket | None
    evidence_snippets: list[str]
    reasons: list[str]
    concerns: list[str]
    confidence: float
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "StructuredReview":
        required = {"verdict", "downgrade_to", "evidence_snippets", "reasons", "concerns", "confidence"}
        missing = sorted(required - data.keys())
        if missing:
            raise ValueError(f"missing required structured review fields: {', '.join(missing)}")
        verdict = str(data["verdict"])
        if verdict not in {"agree", "downgrade", "invalid_unsupported"}:
            raise ValueError("verdict must be agree, downgrade, or invalid_unsupported")
        downgrade_to = data["downgrade_to"]
        confidence = float(data["confidence"])
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be between 0 and 1")
        return cls(
            verdict=verdict,
            downgrade_to=DecisionBucket(str(downgrade_to)) if downgrade_to else None,
            evidence_snippets=[str(value) for value in data["evidence_snippets"]],
            reasons=[str(value) for value in data["reasons"]],
            concerns=[str(value) for value in data["concerns"]],
            confidence=confidence,
            raw=dict(data),
        )


@dataclass(frozen=True)
class ScreeningRules:
    buckets: dict[str, str]
    career_value: dict[str, int]
    preferences: dict[str, dict[str, str]]
    reviewer: dict[str, Any]


@dataclass(frozen=True)
class DecisionArtifacts:
    final_bucket: DecisionBucket
    reviewer_impact: str
    reasons: list[str]
    concerns: list[str] = field(default_factory=list)
    schema_error: str = ""


def load_screening_rules(path: Path | str = "screening_rules.json") -> ScreeningRules:
    data = json.loads(Path(path).read_text())
    return ScreeningRules(
        buckets=dict(data["buckets"]),
        career_value={str(key): int(value) for key, value in data["career_value"].items()},
        preferences={str(key): dict(value) for key, value in data["preferences"].items()},
        reviewer=dict(data["reviewer"]),
    )
```

Create `screening_rules.json`:

```json
{
  "buckets": {
    "auto_apply_draft": "Auto Apply/Draft",
    "ready_for_review": "Ready For Review",
    "needs_my_preference": "Needs My Preference",
    "reject": "Reject",
    "data_parse_error": "Data/Parse Error"
  },
  "career_value": {
    "scripted_acting": 5,
    "student_indie_film": 4,
    "unpaid_theater": 4,
    "staged_reading": 4,
    "commercial_ugc_speaking": 3,
    "music_video_performance": 3,
    "host_presenter": 3,
    "background_extra": 2,
    "audience_atmosphere": 2,
    "generic_social_media": 2,
    "pure_modeling": 1,
    "brand_promo_little_acting": 1,
    "adult_explicit": 0,
    "mission_mismatch": 0
  },
  "preferences": {
    "active_instagram_tagging": {
      "profile_key": "comfortable_with_active_instagram_tagging",
      "label": "Active Instagram tagging"
    },
    "kissing": {
      "profile_key": "comfortable_with_kissing",
      "label": "Kissing"
    },
    "swimwear": {
      "profile_key": "comfortable_with_swimwear",
      "label": "Swimwear"
    }
  },
  "reviewer": {
    "downgrade_requires_evidence": true,
    "auto_apply_draft_can_downgrade_to": ["ready_for_review"],
    "ready_for_review_can_downgrade_to": ["needs_my_preference", "reject"]
  }
}
```

- [ ] **Step 4: Extend existing model dataclasses**

Modify `src/backstage_agent/models.py`:

```python
@dataclass(frozen=True)
class ScreeningDecision:
    notice: CastingNotice
    score: float
    should_apply: bool
    reasons: list[str]
    concerns: list[str] = field(default_factory=list)
    llm_used: bool = False
    final_bucket: str = ""
    classifier_json: dict = field(default_factory=dict)
    reviewer_impact: str = ""
    schema_error: str = ""


@dataclass(frozen=True)
class ReviewDecision:
    notice: CastingNotice
    status: str
    score: float
    reasons: list[str]
    concerns: list[str] = field(default_factory=list)
    model: str = ""
    reviewer_json: dict = field(default_factory=dict)
    reviewer_impact: str = ""
    schema_error: str = ""
```

Keep the `approved` property unchanged.

- [ ] **Step 5: Run tests to verify task passes**

Run:

```bash
.venv/bin/python -m pytest tests/test_decision_core.py tests/test_screener.py tests/test_project_screener.py tests/test_agent_review_gate.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backstage_agent/decision_core.py src/backstage_agent/models.py screening_rules.json tests/test_decision_core.py
git commit -m "feat: add role decision core schema"
```

---

### Task 2: Deterministic Bucket Resolver

**Files:**
- Modify: `src/backstage_agent/decision_core.py`
- Test: `tests/test_decision_core.py`

**Interfaces:**
- Consumes:
  - `DecisionBucket`
  - `StructuredScreening`
  - `StructuredReview`
  - `ScreeningRules`
- Produces:
  - `resolve_bucket(local_bucket: DecisionBucket | None, screening: StructuredScreening | None, review: StructuredReview | None, rules: ScreeningRules, schema_error: str = "") -> DecisionArtifacts`

- [ ] **Step 1: Add failing resolver tests**

Append to `tests/test_decision_core.py`:

```python
from backstage_agent.decision_core import StructuredReview, resolve_bucket


def _screening(**overrides):
    data = {
        "suggested_bucket": "auto_apply_draft",
        "role_type": "scripted_theater",
        "project_type": "theater",
        "career_value_score": 5,
        "required_preferences": [],
        "missing_preference_keys": [],
        "pay_burden": "low",
        "travel_burden": "low",
        "time_burden": "low",
        "fit_reasons": ["Strong role"],
        "concerns": [],
        "evidence_snippets": ["Lead role"],
        "confidence": 0.9,
    }
    data.update(overrides)
    return StructuredScreening.from_json(data)


def _review(**overrides):
    data = {
        "verdict": "agree",
        "downgrade_to": None,
        "evidence_snippets": [],
        "reasons": ["Looks supported"],
        "concerns": [],
        "confidence": 0.8,
    }
    data.update(overrides)
    return StructuredReview.from_json(data)


def test_resolver_schema_error_wins():
    result = resolve_bucket(
        local_bucket=None,
        screening=None,
        review=None,
        rules=load_screening_rules(),
        schema_error="invalid classifier json",
    )

    assert result.final_bucket is DecisionBucket.DATA_PARSE_ERROR
    assert result.schema_error == "invalid classifier json"


def test_resolver_hard_reject_wins_over_auto_apply():
    result = resolve_bucket(
        local_bucket=DecisionBucket.REJECT,
        screening=_screening(),
        review=_review(),
        rules=load_screening_rules(),
    )

    assert result.final_bucket is DecisionBucket.REJECT
    assert "Local hard reject" in result.reasons[0]


def test_resolver_missing_preference_wins():
    result = resolve_bucket(
        local_bucket=None,
        screening=_screening(
            suggested_bucket="auto_apply_draft",
            missing_preference_keys=["comfortable_with_stage_combat"],
        ),
        review=_review(),
        rules=load_screening_rules(),
    )

    assert result.final_bucket is DecisionBucket.NEEDS_MY_PREFERENCE
    assert result.reviewer_impact == "none"


def test_reviewer_downgrade_with_evidence_changes_auto_apply_to_review():
    result = resolve_bucket(
        local_bucket=None,
        screening=_screening(suggested_bucket="auto_apply_draft"),
        review=_review(
            verdict="downgrade",
            downgrade_to="ready_for_review",
            evidence_snippets=["Schedule is not listed"],
            reasons=["Schedule missing for a multi-day role"],
        ),
        rules=load_screening_rules(),
    )

    assert result.final_bucket is DecisionBucket.READY_FOR_REVIEW
    assert result.reviewer_impact == "downgraded"


def test_reviewer_downgrade_without_evidence_is_ignored():
    result = resolve_bucket(
        local_bucket=None,
        screening=_screening(suggested_bucket="auto_apply_draft"),
        review=_review(
            verdict="downgrade",
            downgrade_to="ready_for_review",
            evidence_snippets=[],
            reasons=["Too optimistic"],
        ),
        rules=load_screening_rules(),
    )

    assert result.final_bucket is DecisionBucket.AUTO_APPLY_DRAFT
    assert result.reviewer_impact == "unsupported_downgrade"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_decision_core.py -v
```

Expected: FAIL because `resolve_bucket` is missing.

- [ ] **Step 3: Implement resolver**

Append to `src/backstage_agent/decision_core.py`:

```python
def resolve_bucket(
    local_bucket: DecisionBucket | None,
    screening: StructuredScreening | None,
    review: StructuredReview | None,
    rules: ScreeningRules,
    schema_error: str = "",
) -> DecisionArtifacts:
    if schema_error:
        return DecisionArtifacts(
            final_bucket=DecisionBucket.DATA_PARSE_ERROR,
            reviewer_impact="none",
            reasons=["Structured model output failed validation."],
            schema_error=schema_error,
        )
    if local_bucket is DecisionBucket.REJECT:
        return DecisionArtifacts(
            final_bucket=DecisionBucket.REJECT,
            reviewer_impact="none",
            reasons=["Local hard reject took precedence."],
        )
    if screening is None:
        return DecisionArtifacts(
            final_bucket=DecisionBucket.DATA_PARSE_ERROR,
            reviewer_impact="none",
            reasons=["Structured screening output was unavailable."],
            schema_error="missing structured screening output",
        )
    if screening.missing_preference_keys:
        return DecisionArtifacts(
            final_bucket=DecisionBucket.NEEDS_MY_PREFERENCE,
            reviewer_impact="none",
            reasons=[
                "Required preference is missing: "
                + ", ".join(screening.missing_preference_keys)
            ],
            concerns=screening.concerns,
        )
    reviewer_impact = "none"
    final_bucket = screening.suggested_bucket
    reasons = list(screening.fit_reasons)
    concerns = list(screening.concerns)
    if review and review.verdict == "downgrade" and review.downgrade_to:
        allowed = _downgrade_allowed(final_bucket, review.downgrade_to, rules)
        if allowed and review.evidence_snippets:
            final_bucket = review.downgrade_to
            reviewer_impact = "downgraded"
            reasons.extend(review.reasons)
            concerns.extend(review.concerns)
        else:
            reviewer_impact = "unsupported_downgrade"
            concerns.append("Reviewer downgrade ignored because it lacked evidence or was not allowed.")
    elif review and review.verdict == "invalid_unsupported":
        reviewer_impact = "invalid_unsupported"
        concerns.extend(review.concerns)
    return DecisionArtifacts(
        final_bucket=final_bucket,
        reviewer_impact=reviewer_impact,
        reasons=reasons or ["Final bucket resolved from structured screening output."],
        concerns=concerns,
    )


def _downgrade_allowed(
    current: DecisionBucket,
    requested: DecisionBucket,
    rules: ScreeningRules,
) -> bool:
    reviewer_rules = rules.reviewer
    if current is DecisionBucket.AUTO_APPLY_DRAFT:
        return requested.value in reviewer_rules["auto_apply_draft_can_downgrade_to"]
    if current is DecisionBucket.READY_FOR_REVIEW:
        return requested.value in reviewer_rules["ready_for_review_can_downgrade_to"]
    return False
```

- [ ] **Step 4: Run resolver tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_decision_core.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/decision_core.py tests/test_decision_core.py
git commit -m "feat: resolve final decision buckets"
```

---

### Task 3: Structured First LLM Screening With Repair Retry

**Files:**
- Modify: `src/backstage_agent/screener.py`
- Modify: `src/backstage_agent/project_screener.py`
- Test: `tests/test_structured_screening.py`

**Interfaces:**
- Consumes:
  - `StructuredScreening.from_json`
  - `DecisionBucket.DATA_PARSE_ERROR`
- Produces:
  - `ScreeningDecision.classifier_json`
  - `ScreeningDecision.final_bucket`
  - `ScreeningDecision.schema_error`

- [ ] **Step 1: Write failing tests for structured role screening and repair retry**

Create `tests/test_structured_screening.py`:

```python
from types import SimpleNamespace

from backstage_agent.models import ActorProfile, CastingNotice
from backstage_agent.screener import RoleScreener
from backstage_agent.settings import Settings


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        content = self.responses.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _settings(tmp_path):
    return Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="deepseek-v4-pro",
        max_llm_calls_per_scan=5,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )


def _profile():
    return ActorProfile(
        name="Actor",
        location="Fremont, CA",
        age_range="25-40",
        genders=["female"],
        ethnicities=["Asian"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=["theater"],
        max_travel_miles=60,
        cover_note_template="Hello",
    )


def _notice():
    return CastingNotice(
        source_message_id="m1",
        title="Play - Lead",
        project="Play",
        role="Lead",
        location="Fremont, CA",
        compensation="Paid",
        description="Lead, Female, 25-40",
        application_url=None,
        raw_text="Lead, Female, 25-40",
    )


def _valid_json():
    return """{
      "suggested_bucket": "auto_apply_draft",
      "role_type": "scripted_acting",
      "project_type": "theater",
      "career_value_score": 5,
      "required_preferences": [],
      "missing_preference_keys": [],
      "pay_burden": "low",
      "travel_burden": "low",
      "time_burden": "low",
      "fit_reasons": ["Named acting role"],
      "concerns": [],
      "evidence_snippets": ["Lead, Female, 25-40"],
      "confidence": 0.9
    }"""


def test_role_screener_records_structured_classifier_output(tmp_path):
    screener = RoleScreener(_settings(tmp_path), _profile())
    screener._client = FakeClient([_valid_json()])

    decision = screener.screen(_notice())

    assert decision.llm_used is True
    assert decision.final_bucket == "auto_apply_draft"
    assert decision.classifier_json["career_value_score"] == 5
    assert decision.schema_error == ""


def test_role_screener_repairs_invalid_classifier_once(tmp_path):
    screener = RoleScreener(_settings(tmp_path), _profile())
    screener._client = FakeClient(["{}", _valid_json()])

    decision = screener.screen(_notice())

    assert screener._client.chat.completions.calls == 2
    assert decision.final_bucket == "auto_apply_draft"
    assert decision.schema_error == ""


def test_role_screener_returns_data_parse_error_after_failed_repair(tmp_path):
    screener = RoleScreener(_settings(tmp_path), _profile())
    screener._client = FakeClient(["{}", "{}"])

    decision = screener.screen(_notice())

    assert decision.should_apply is False
    assert decision.final_bucket == "data_parse_error"
    assert "missing required structured screening fields" in decision.schema_error
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_structured_screening.py -v
```

Expected: FAIL because screeners still parse legacy free-form JSON.

- [ ] **Step 3: Add structured parse helper to role screener**

Modify `src/backstage_agent/screener.py` imports:

```python
from .decision_core import DecisionBucket, StructuredScreening
```

Replace `_llm_screen` JSON handling with:

```python
    def _llm_screen(self, notice: CastingNotice) -> ScreeningDecision:
        self._llm_calls += 1
        content = self._call_structured_llm(notice, repair_error="")
        try:
            structured = StructuredScreening.from_json(json.loads(content or "{}"))
        except (ValueError, json.JSONDecodeError) as exc:
            repair_content = self._call_structured_llm(notice, repair_error=str(exc))
            try:
                structured = StructuredScreening.from_json(json.loads(repair_content or "{}"))
            except (ValueError, json.JSONDecodeError) as repair_exc:
                return ScreeningDecision(
                    notice=notice,
                    score=0.0,
                    should_apply=False,
                    reasons=["Rejected because structured role screening output was invalid."],
                    concerns=[],
                    llm_used=True,
                    final_bucket=DecisionBucket.DATA_PARSE_ERROR.value,
                    classifier_json={},
                    schema_error=str(repair_exc),
                )
        should_apply = structured.suggested_bucket is DecisionBucket.AUTO_APPLY_DRAFT
        return ScreeningDecision(
            notice=notice,
            score=structured.confidence,
            should_apply=should_apply,
            reasons=structured.fit_reasons,
            concerns=structured.concerns,
            llm_used=True,
            final_bucket=structured.suggested_bucket.value,
            classifier_json=structured.raw,
        )
```

Add helper:

```python
    def _call_structured_llm(self, notice: CastingNotice, repair_error: str) -> str:
        repair_instruction = (
            f"Previous JSON failed validation: {repair_error}. Return only corrected JSON. "
            if repair_error
            else ""
        )
        response = self._client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        repair_instruction
                        + "Classify this casting role using the structured schema. "
                        "Return JSON with suggested_bucket, role_type, project_type, "
                        "career_value_score, required_preferences, missing_preference_keys, "
                        "pay_burden, travel_burden, time_burden, fit_reasons, concerns, "
                        "evidence_snippets, and confidence. suggested_bucket must be one "
                        "of auto_apply_draft, ready_for_review, needs_my_preference, reject, "
                        "or data_parse_error. career_value_score must be 0-5. confidence "
                        "must be 0-1. Use exact notice snippets for evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "actor_profile": asdict(self.profile),
                            "casting_notice": asdict(notice),
                            "minimum_score": self.settings.min_match_score,
                        },
                        default=str,
                    ),
                },
            ],
        )
        return response.choices[0].message.content or "{}"
```

- [ ] **Step 4: Mirror structured parse helper in project screener**

Modify `src/backstage_agent/project_screener.py` imports:

```python
from .decision_core import DecisionBucket, StructuredScreening
```

Apply the same `_llm_screen` and `_call_structured_llm` pattern, changing labels from role to project and `project_notice` in the user JSON. Use the same returned `ScreeningDecision` fields.

- [ ] **Step 5: Run structured screening tests and existing screener tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_structured_screening.py tests/test_screener.py tests/test_project_screener.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backstage_agent/screener.py src/backstage_agent/project_screener.py tests/test_structured_screening.py
git commit -m "feat: structure first pass screening output"
```

---

### Task 4: Structured Downgrade-Only Reviewer

**Files:**
- Modify: `src/backstage_agent/reviewer.py`
- Test: `tests/test_structured_reviewer.py`

**Interfaces:**
- Consumes:
  - `StructuredReview.from_json`
- Produces:
  - `ReviewDecision.reviewer_json`
  - `ReviewDecision.reviewer_impact`
  - `ReviewDecision.schema_error`

- [ ] **Step 1: Write failing reviewer tests**

Create `tests/test_structured_reviewer.py`:

```python
from types import SimpleNamespace

from backstage_agent.models import ActorProfile, CastingNotice
from backstage_agent.reviewer import DecisionReviewer
from backstage_agent.settings import Settings


class FakeCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.responses.pop(0)))]
        )


class FakeClient:
    def __init__(self, responses):
        self.chat = SimpleNamespace(completions=FakeCompletions(responses))


def _settings(tmp_path):
    return Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="deepseek-v4-pro",
        max_llm_calls_per_scan=5,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
        reviewer_provider="openai",
        reviewer_model="gpt-5.4-mini",
        max_reviewer_calls_per_scan=5,
    )


def _profile():
    return ActorProfile(
        name="Actor",
        location="Fremont, CA",
        age_range="25-40",
        genders=["female"],
        ethnicities=["Asian"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=["theater"],
        max_travel_miles=60,
        cover_note_template="Hello",
    )


def _notice():
    return CastingNotice(
        source_message_id="m1",
        title="Play - Lead",
        project="Play",
        role="Lead",
        location="Fremont, CA",
        compensation="Paid",
        description="Lead, Female, 25-40",
        application_url=None,
        raw_text="Lead, Female, 25-40",
    )


def _review_json(verdict="agree", downgrade_to=None, evidence=None):
    evidence = evidence or []
    return """{
      "verdict": "%s",
      "downgrade_to": %s,
      "evidence_snippets": %s,
      "reasons": ["Review completed"],
      "concerns": [],
      "confidence": 0.82
    }""" % (
        verdict,
        "null" if downgrade_to is None else f'"{downgrade_to}"',
        str(evidence).replace("'", '"'),
    )


def test_reviewer_records_structured_agreement(tmp_path):
    reviewer = DecisionReviewer(_settings(tmp_path), _profile())
    reviewer._client = FakeClient([_review_json()])

    decision = reviewer.review(_notice())

    assert decision.status == "approved"
    assert decision.reviewer_json["verdict"] == "agree"
    assert decision.schema_error == ""


def test_reviewer_records_downgrade_with_evidence(tmp_path):
    reviewer = DecisionReviewer(_settings(tmp_path), _profile())
    reviewer._client = FakeClient([
        _review_json("downgrade", "ready_for_review", ["Schedule unclear"])
    ])

    decision = reviewer.review(_notice())

    assert decision.status == "hold"
    assert decision.reviewer_impact == "downgrade"
    assert decision.reviewer_json["downgrade_to"] == "ready_for_review"


def test_reviewer_repairs_invalid_json_once(tmp_path):
    reviewer = DecisionReviewer(_settings(tmp_path), _profile())
    reviewer._client = FakeClient(["{}", _review_json()])

    decision = reviewer.review(_notice())

    assert reviewer._client.chat.completions.calls == 2
    assert decision.status == "approved"
    assert decision.schema_error == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_structured_reviewer.py -v
```

Expected: FAIL because reviewer still expects legacy `status` JSON.

- [ ] **Step 3: Implement structured reviewer parsing**

Modify `src/backstage_agent/reviewer.py` imports:

```python
from .decision_core import StructuredReview
```

Update `_llm_review` after API response to parse structured review. Use this mapping:

```python
def _status_from_structured_review(review: StructuredReview) -> str:
    if review.verdict == "agree":
        return "approved"
    if review.verdict == "downgrade":
        return "hold" if review.downgrade_to and review.evidence_snippets else "approved"
    return "hold"
```

Replace JSON parse block with:

```python
        content = response.choices[0].message.content or "{}"
        try:
            structured = StructuredReview.from_json(json.loads(content))
        except (ValueError, json.JSONDecodeError) as exc:
            repair_content = self._call_reviewer_llm(notice, system_prompt, repair_error=str(exc))
            try:
                structured = StructuredReview.from_json(json.loads(repair_content or "{}"))
            except (ValueError, json.JSONDecodeError) as repair_exc:
                return ReviewDecision(
                    notice=notice,
                    status="error",
                    score=0.0,
                    reasons=["Reviewer returned invalid structured JSON."],
                    concerns=[],
                    model=self.settings.reviewer_model,
                    schema_error=str(repair_exc),
                )

        return ReviewDecision(
            notice=notice,
            status=_status_from_structured_review(structured),
            score=structured.confidence,
            reasons=structured.reasons,
            concerns=structured.concerns,
            model=self.settings.reviewer_model,
            reviewer_json=structured.raw,
            reviewer_impact="downgrade" if structured.verdict == "downgrade" else structured.verdict,
        )
```

Move the existing OpenAI call body into:

```python
    def _call_reviewer_llm(self, notice: CastingNotice, system_prompt: str, repair_error: str = "") -> str:
        repair_instruction = (
            f"Previous reviewer JSON failed validation: {repair_error}. Return only corrected JSON. "
            if repair_error
            else ""
        )
        token_limit_param = (
            {"max_completion_tokens": 1000}
            if self.settings.reviewer_provider.strip().lower() == "openai"
            else {"max_tokens": 1000}
        )
        response = self._client.chat.completions.create(
            model=self.settings.reviewer_model,
            temperature=0,
            response_format={"type": "json_object"},
            **token_limit_param,
            messages=[
                {"role": "system", "content": repair_instruction + system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "actor_profile": asdict(self.profile),
                            "casting_notice": asdict(notice),
                            "minimum_score": self.settings.min_match_score,
                        },
                        default=str,
                    ),
                },
            ],
        )
        return response.choices[0].message.content or "{}"
```

- [ ] **Step 4: Run reviewer tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_structured_reviewer.py tests/test_agent_review_gate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/reviewer.py tests/test_structured_reviewer.py
git commit -m "feat: structure reviewer validation output"
```

---

### Task 5: Persist Structured Decision Artifacts

**Files:**
- Modify: `src/backstage_agent/storage.py`
- Test: `tests/test_storage_dashboard.py`

**Interfaces:**
- Consumes:
  - `ScreeningDecision.final_bucket`
  - `ScreeningDecision.classifier_json`
  - `ScreeningDecision.reviewer_impact`
  - `ScreeningDecision.schema_error`
  - `ReviewDecision.reviewer_json`
  - `ReviewDecision.reviewer_impact`
  - `ReviewDecision.schema_error`
- Produces:
  - SQLite columns: `final_bucket`, `classifier_json`, `reviewer_json`, `reviewer_impact`, `schema_error`
  - `search_decisions()` rows include these fields.
  - `DecisionStore.update_decision_artifacts(decision_id: int, artifacts: DecisionArtifacts) -> None`

- [ ] **Step 1: Write failing storage test**

Append to `tests/test_storage_dashboard.py`:

```python
def test_store_persists_structured_decision_artifacts(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    decision = ScreeningDecision(
        notice=_notice("Structured Role"),
        score=0.9,
        should_apply=True,
        reasons=["Structured pass"],
        llm_used=True,
        final_bucket="auto_apply_draft",
        classifier_json={"career_value_score": 5},
        reviewer_impact="none",
    )

    decision_id = store.record_decision(decision)
    store.record_review(
        decision_id,
        ReviewDecision(
            notice=decision.notice,
            status="approved",
            score=0.8,
            reasons=["Reviewer agreed"],
            reviewer_json={"verdict": "agree"},
            reviewer_impact="agree",
        ),
    )

    rows = store.search_decisions()

    assert rows[0]["final_bucket"] == "auto_apply_draft"
    assert rows[0]["classifier_json"] == '{"career_value_score": 5}'
    assert rows[0]["reviewer_json"] == '{"verdict": "agree"}'
    assert rows[0]["reviewer_impact"] == "agree"


def test_store_updates_final_bucket_after_reviewer_resolution(tmp_path):
    from backstage_agent.decision_core import DecisionArtifacts, DecisionBucket

    store = DecisionStore(tmp_path / "db.sqlite3")
    decision = ScreeningDecision(
        notice=_notice("Downgraded Role"),
        score=0.9,
        should_apply=True,
        reasons=["Structured pass"],
        llm_used=True,
        final_bucket="auto_apply_draft",
        classifier_json={"suggested_bucket": "auto_apply_draft"},
    )
    decision_id = store.record_decision(decision)

    store.update_decision_artifacts(
        decision_id,
        DecisionArtifacts(
            final_bucket=DecisionBucket.READY_FOR_REVIEW,
            reviewer_impact="downgraded",
            reasons=["Reviewer found missing schedule evidence."],
            concerns=["Schedule is not listed."],
        ),
    )

    rows = store.search_decisions()

    assert rows[0]["final_bucket"] == "ready_for_review"
    assert rows[0]["reviewer_impact"] == "downgraded"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/test_storage_dashboard.py::test_store_persists_structured_decision_artifacts -v
```

Expected: FAIL because columns and row fields do not exist.

- [ ] **Step 3: Add schema columns and persistence**

In `DecisionStore._ensure_schema()`, add columns to the `decisions` table creation:

```sql
final_bucket TEXT,
classifier_json TEXT,
reviewer_json TEXT,
reviewer_impact TEXT,
schema_error TEXT
```

Add these entries to the lightweight migration column map:

```python
"final_bucket": "TEXT",
"classifier_json": "TEXT",
"reviewer_json": "TEXT",
"reviewer_impact": "TEXT",
"schema_error": "TEXT",
```

In `record_decision`, include:

```python
json.dumps(decision.classifier_json, sort_keys=True),
decision.final_bucket,
decision.reviewer_impact,
decision.schema_error,
```

In `record_review`, update:

```python
reviewer_json = ?,
reviewer_impact = ?,
schema_error = COALESCE(NULLIF(?, ''), schema_error)
```

with:

```python
json.dumps(review.reviewer_json, sort_keys=True),
review.reviewer_impact,
review.schema_error,
```

In `search_decisions`, select and return:

```sql
d.final_bucket, d.classifier_json, d.reviewer_json, d.reviewer_impact, d.schema_error
```

Add a store update helper:

```python
def update_decision_artifacts(self, decision_id: int, artifacts: DecisionArtifacts) -> None:
    with self._connect() as conn:
        conn.execute(
            """
            UPDATE decisions
            SET final_bucket = ?,
                reviewer_impact = ?,
                reasons_json = ?,
                concerns_json = ?,
                schema_error = COALESCE(NULLIF(?, ''), schema_error)
            WHERE id = ?
            """,
            (
                artifacts.final_bucket.value,
                artifacts.reviewer_impact,
                json.dumps(artifacts.reasons),
                json.dumps(artifacts.concerns),
                artifacts.schema_error,
                decision_id,
            ),
        )
```

Add the import near the top of `src/backstage_agent/storage.py`:

```python
from .decision_core import DecisionArtifacts
```

- [ ] **Step 4: Run storage tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_storage_dashboard.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/storage.py tests/test_storage_dashboard.py
git commit -m "feat: persist structured decision artifacts"
```

---

### Task 6: Use Final Buckets In Agent Flow

**Files:**
- Modify: `src/backstage_agent/agent.py`
- Test: `tests/test_agent_review_gate.py`

**Interfaces:**
- Consumes:
  - `ScreeningDecision.final_bucket`
  - `ReviewDecision.reviewer_json`
  - `resolve_bucket(...)`
  - `DecisionStore.update_decision_artifacts(decision_id, artifacts)`
- Produces:
  - Project role screening continues only when project final bucket allows it.
  - Role application drafting happens only for final bucket `auto_apply_draft`.
  - Reviewer downgrades update the stored final bucket before application drafting.

- [ ] **Step 1: Add failing agent-flow tests**

Append to `tests/test_agent_review_gate.py`:

```python
def test_scan_does_not_screen_roles_when_project_bucket_rejects(monkeypatch):
    from backstage_agent import agent as agent_module

    notice = SimpleNamespace(
        role_key="role-should-not-screen",
        shooting_locations="Los Angeles",
        shooting_dates="July 2026",
    )
    project = ProjectNotice(
        source_message_id="m1",
        title="Project",
        project_url="https://example.com",
        description="Project",
        raw_text="Project",
        project_key="project-key",
    )
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="approved")
    backstage_agent.project_screener = FakeScreener(should_apply=False)
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = backstage_agent.scan(limit=1, days=1)

    assert result.notices_seen == 0
    assert len(result.decisions) == 0


def test_scan_drafts_only_auto_apply_bucket(monkeypatch):
    from backstage_agent import agent as agent_module

    class ReadyReviewScreener(FakeScreener):
        def screen(self, notice):
            decision = super().screen(notice)
            return ScreeningDecision(
                notice=decision.notice,
                score=decision.score,
                should_apply=True,
                reasons=decision.reasons,
                final_bucket="ready_for_review",
            )

    notice = SimpleNamespace(
        role_key="role-ready-review",
        shooting_locations="Los Angeles",
        shooting_dates="July 2026",
    )
    project = ProjectNotice(
        source_message_id="m1",
        title="Project",
        project_url="https://example.com",
        description="Project",
        raw_text="Project",
        project_key="project-key",
    )
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="approved")
    backstage_agent.screener = ReadyReviewScreener(should_apply=True)
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = backstage_agent.scan(limit=1, days=1)

    assert len(result.reviews) == 1
    assert len(result.applications) == 0


def test_scan_uses_reviewer_downgrade_before_application(monkeypatch):
    from backstage_agent import agent as agent_module

    class AutoApplyScreener(FakeScreener):
        def screen(self, notice):
            decision = super().screen(notice)
            return ScreeningDecision(
                notice=decision.notice,
                score=decision.score,
                should_apply=True,
                reasons=decision.reasons,
                final_bucket="auto_apply_draft",
                classifier_json={
                    "suggested_bucket": "auto_apply_draft",
                    "role_type": "scripted_acting",
                    "project_type": "theater",
                    "career_value_score": 5,
                    "required_preferences": [],
                    "missing_preference_keys": [],
                    "pay_burden": "low",
                    "travel_burden": "low",
                    "time_burden": "low",
                    "fit_reasons": ["Strong role"],
                    "concerns": [],
                    "evidence_snippets": ["Lead role"],
                    "confidence": 0.9,
                },
            )

    class DowngradeReviewer(FakeReviewer):
        def review(self, notice):
            return ReviewDecision(
                notice=notice,
                status="hold",
                score=0.7,
                reasons=["Schedule is unclear"],
                reviewer_json={
                    "verdict": "downgrade",
                    "downgrade_to": "ready_for_review",
                    "evidence_snippets": ["No schedule listed"],
                    "reasons": ["No schedule listed"],
                    "concerns": ["Schedule is unclear"],
                    "confidence": 0.7,
                },
                reviewer_impact="downgrade",
            )

    notice = SimpleNamespace(
        role_key="role-downgraded",
        shooting_locations="Los Angeles",
        shooting_dates="July 2026",
    )
    project = ProjectNotice(
        source_message_id="m1",
        title="Project",
        project_url="https://example.com",
        description="Project",
        raw_text="Project",
        project_key="project-key",
    )
    backstage_agent = _agent_with(notice, should_apply=True, reviewer_status="approved")
    backstage_agent.screener = AutoApplyScreener(should_apply=True)
    backstage_agent.reviewer = DowngradeReviewer(status="hold")
    monkeypatch.setattr(agent_module, "parse_project_notices", lambda message: [project])
    monkeypatch.setattr(agent_module, "parse_project_page_roles", lambda project, html: [notice])
    backstage_agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = backstage_agent.scan(limit=1, days=1)

    assert len(result.reviews) == 1
    assert len(result.applications) == 0
```

- [ ] **Step 2: Run tests to verify expected failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_agent_review_gate.py -v
```

Expected: second new test FAILS because approved reviewer currently triggers application regardless of final bucket.

- [ ] **Step 3: Add bucket helpers and use them in scan**

In `src/backstage_agent/agent.py`, import:

```python
from dataclasses import replace

from .decision_core import DecisionArtifacts, DecisionBucket
from .decision_core import StructuredReview, StructuredScreening, load_screening_rules, resolve_bucket
```

Add helpers near `BackstageAgent`:

```python
def _allows_role_screening(decision: ScreeningDecision, review: ReviewDecision | None = None) -> bool:
    bucket = decision.final_bucket or (
        DecisionBucket.AUTO_APPLY_DRAFT.value if decision.should_apply else DecisionBucket.REJECT.value
    )
    if bucket in {DecisionBucket.REJECT.value, DecisionBucket.DATA_PARSE_ERROR.value}:
        return False
    if review and not review.approved:
        return False
    return bucket in {
        DecisionBucket.AUTO_APPLY_DRAFT.value,
        DecisionBucket.READY_FOR_REVIEW.value,
        DecisionBucket.NEEDS_MY_PREFERENCE.value,
    }


def _allows_application_draft(decision: ScreeningDecision, review: ReviewDecision) -> bool:
    return decision.final_bucket == DecisionBucket.AUTO_APPLY_DRAFT.value and review.approved
```

Add a post-review resolution helper:

```python
def _resolve_after_review(
    decision: ScreeningDecision,
    review: ReviewDecision,
) -> tuple[ScreeningDecision, DecisionArtifacts | None]:
    if not decision.classifier_json or not review.reviewer_json:
        return decision, None
    artifacts = resolve_bucket(
        local_bucket=None,
        screening=StructuredScreening.from_json(decision.classifier_json),
        review=StructuredReview.from_json(review.reviewer_json),
        rules=load_screening_rules(),
        schema_error=decision.schema_error or review.schema_error,
    )
    return (
        replace(
            decision,
            final_bucket=artifacts.final_bucket.value,
            reasons=artifacts.reasons,
            concerns=artifacts.concerns,
            reviewer_impact=artifacts.reviewer_impact,
            schema_error=artifacts.schema_error,
        ),
        artifacts,
    )
```

Replace project gate checks:

```python
if not project_decision.should_apply:
    continue
...
if not project_review.approved:
    continue
```

with:

```python
if not _allows_role_screening(project_decision):
    continue
...
if not _allows_role_screening(project_decision, project_review):
    continue
```

Replace role application check:

```python
if review.approved:
```

with:

```python
decision, artifacts = _resolve_after_review(decision, review)
if artifacts is not None:
    self.store.update_decision_artifacts(decision_id, artifacts)
if _allows_application_draft(decision, review):
```

When `decision.classifier_json` or `review.reviewer_json` is empty, `_resolve_after_review` returns `(decision, None)`. This skips the `update_decision_artifacts` call and preserves compatibility for legacy local decisions and tests.

- [ ] **Step 4: Run agent flow tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_agent_review_gate.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/agent.py tests/test_agent_review_gate.py
git commit -m "feat: gate agent flow on final buckets"
```

---

### Task 7: Minimal Dashboard And CLI Exposure

**Files:**
- Modify: `src/backstage_agent/ui.py`
- Modify: `src/backstage_agent/cli.py`
- Test: `tests/test_ui_labels.py`
- Test: `tests/test_cli_summary.py`

**Interfaces:**
- Consumes:
  - `final_bucket`
  - `classifier_json`
  - `reviewer_json`
  - `reviewer_impact`
- Produces:
  - Dashboard label includes final bucket when present.
  - Dashboard detail includes reviewer impact and expandable raw model JSON.
  - CLI summary includes final bucket counts while preserving existing summary wording.

- [ ] **Step 1: Add failing UI label tests**

Append to `tests/test_ui_labels.py`:

```python
from backstage_agent.ui import _final_bucket_label, _model_detail


def test_final_bucket_label_prefers_structured_bucket():
    assert _final_bucket_label({"final_bucket": "auto_apply_draft"}) == "Auto Apply/Draft"
    assert _final_bucket_label({"final_bucket": "ready_for_review"}) == "Ready For Review"
    assert _final_bucket_label({"final_bucket": "needs_my_preference"}) == "Needs My Preference"
    assert _final_bucket_label({"final_bucket": "data_parse_error"}) == "Data/Parse Error"


def test_model_detail_shows_reviewer_impact_and_raw_json():
    html = _model_detail(
        {
            "classifier_json": '{"suggested_bucket": "auto_apply_draft"}',
            "reviewer_json": '{"verdict": "downgrade"}',
            "reviewer_impact": "downgraded",
        }
    )

    assert "Reviewer impact: downgraded" in html
    assert "suggested_bucket" in html
    assert "verdict" in html
```

- [ ] **Step 2: Run UI tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_labels.py -v
```

Expected: FAIL because helper functions are missing.

- [ ] **Step 3: Implement dashboard helpers**

In `src/backstage_agent/ui.py`, add:

```python
FINAL_BUCKET_LABELS = {
    "auto_apply_draft": "Auto Apply/Draft",
    "ready_for_review": "Ready For Review",
    "needs_my_preference": "Needs My Preference",
    "reject": "Reject",
    "data_parse_error": "Data/Parse Error",
}


def _final_bucket_label(row: dict) -> str:
    bucket = row.get("final_bucket") or ""
    if bucket:
        return FINAL_BUCKET_LABELS.get(bucket, bucket)
    return _decision_status(row)


def _model_detail(row: dict) -> str:
    classifier = row.get("classifier_json") or "{}"
    reviewer = row.get("reviewer_json") or "{}"
    impact = row.get("reviewer_impact") or "none"
    return (
        "<details class=\"model-detail\">"
        "<summary>Show model details</summary>"
        f"<p>Reviewer impact: {_esc(impact)}</p>"
        f"<pre>{_esc(classifier)}</pre>"
        f"<pre>{_esc(reviewer)}</pre>"
        "</details>"
    )
```

In the decision row rendering, replace status label calls with `_final_bucket_label(row)` and include `_model_detail(row)` below reviewer detail.

- [ ] **Step 4: Add CLI summary bucket-count test**

Update `tests/test_cli_summary.py` with:

```python
def test_summary_includes_final_bucket_counts():
    notice = _notice("Auto Role")
    result = SimpleNamespace(
        messages_seen=1,
        projects_seen=1,
        notices_seen=1,
        project_decisions=[],
        project_reviews=[],
        decisions=[
            ScreeningDecision(
                notice=notice,
                score=0.9,
                should_apply=True,
                reasons=["ok"],
                final_bucket="auto_apply_draft",
            )
        ],
        reviews=[],
        applications=[],
    )

    summary = _summary_lines(result)

    assert "Buckets: Auto Apply/Draft 1" in summary
```

- [ ] **Step 5: Implement CLI bucket summary**

In `src/backstage_agent/cli.py`, add bucket count formatting inside the existing summary helper:

```python
def _bucket_summary(decisions: list[ScreeningDecision]) -> str:
    labels = {
        "auto_apply_draft": "Auto Apply/Draft",
        "ready_for_review": "Ready For Review",
        "needs_my_preference": "Needs My Preference",
        "reject": "Reject",
        "data_parse_error": "Data/Parse Error",
    }
    counts = {key: 0 for key in labels}
    for decision in decisions:
        if decision.final_bucket in counts:
            counts[decision.final_bucket] += 1
    parts = [f"{label} {counts[key]}" for key, label in labels.items() if counts[key]]
    return "Buckets: " + ", ".join(parts) if parts else ""
```

Append the non-empty bucket summary to existing summary lines.

- [ ] **Step 6: Run UI and CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_labels.py tests/test_cli_summary.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/backstage_agent/ui.py src/backstage_agent/cli.py tests/test_ui_labels.py tests/test_cli_summary.py
git commit -m "feat: expose final buckets and reviewer impact"
```

---

### Task 8: Documentation And Focused Regression Pass

**Files:**
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/module-guide.md`

**Interfaces:**
- Consumes:
  - Completed Tasks 1-7.
- Produces:
  - Documentation reflects structured decision core, final buckets, and migration state.

- [ ] **Step 1: Update project state**

In `PROJECT_STATE.md`, update `Current Capabilities` with:

```markdown
- Structured role/project decision core with five final buckets, structured first-pass classifier output, downgrade-only reviewer validation, and deterministic bucket resolution.
```

Update `In Progress` with:

```markdown
- Dashboard grouping, preference-answer controls, rule suggestion queues, and full screening-rules editing remain follow-up work after the decision contract stabilizes.
```

- [ ] **Step 2: Update changelog**

In `CHANGELOG.md`, under `Unreleased -> Added`, add:

```markdown
- Added a structured role-selection decision core with five final buckets, classifier/reviewer artifacts, reviewer impact tracking, and deterministic bucket resolution.
```

- [ ] **Step 3: Update module guide**

In `docs/module-guide.md`, under `Screening And Review`, add:

```markdown
- Use `src/backstage_agent/decision_core.py` for final bucket definitions, structured classifier/reviewer validation, rules loading, and deterministic bucket resolution.
```

- [ ] **Step 4: Run focused regression tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_decision_core.py tests/test_structured_screening.py tests/test_structured_reviewer.py tests/test_agent_review_gate.py tests/test_storage_dashboard.py tests/test_ui_labels.py tests/test_cli_summary.py tests/test_screener.py tests/test_project_screener.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add PROJECT_STATE.md CHANGELOG.md docs/module-guide.md
git commit -m "docs: describe structured role selection core"
```

---

## Completion Checklist

- [ ] Final bucket enum and structured model artifacts exist.
- [ ] Local hard reject precedence is tested.
- [ ] Missing preferences resolve to `Needs My Preference`.
- [ ] Reviewer downgrades require exact evidence to affect final bucket.
- [ ] Invalid first LLM and reviewer output gets one repair retry.
- [ ] Structured artifacts are persisted.
- [ ] Project screening remains before role screening.
- [ ] Role application drafting only uses role-level `Auto Apply/Draft`.
- [ ] Dashboard exposes final bucket, reviewer impact, and expandable raw model output.
- [ ] CLI summary exposes final bucket counts.
- [ ] Documentation describes the new decision core and remaining follow-up work.
