# Candidate Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the candidate-first mutual-selection scoring pipeline described in `docs/superpowers/specs/2026-07-13-candidate-scoring-design.md`.

**Architecture:** Add a scoring domain beside the existing decision bucket flow, then migrate orchestration to generate candidates, extract features, match local requirements, score deterministically, rank, display, and collect feedback. The LLM produces structured features only; Python owns matching, scoring, score caps, bands, re-ranking, and calibration proposals.

**Tech Stack:** Python dataclasses, SQLite via `sqlite3`, JSON config files, existing OpenAI-compatible chat client pattern, pytest.

## Global Constraints

- Always produce a score for every generated candidate.
- Treat casting as mutual selection: their requirements and my requirements are both evaluated.
- Use the LLM for structured feature extraction only, not scoring.
- Use local rules and stored actor facts to evaluate project/role requirements.
- Improve scoring rules and scoring code, not prompts, when human feedback shows a scoring mistake.
- Keep drafting/application as a separate human-approved workflow.
- Do not restore hard project-level filtering; project evaluation is a score component.
- No live Backstage submission.
- No automatic scoring-rule mutation.
- No inferred roles beyond parsed explicit roles and project-only opportunities.
- Keep daily scan defaults and dry-run safety unchanged.

---

## File Structure

- Create `src/backstage_agent/candidate_models.py` for candidate, feature, requirement-match, score, feedback, and calibration dataclasses/enums.
- Create `src/backstage_agent/candidate_generation.py` for turning parsed projects and roles into `CandidateInput` objects.
- Create `src/backstage_agent/feature_extractor.py` for LLM feature extraction schemas and prompt plumbing.
- Create `src/backstage_agent/requirement_matcher.py` for local mutual-selection requirement checks against `ActorProfile`.
- Create `src/backstage_agent/scoring.py` for loading scoring rules, deterministic scoring, bands, caps, and re-ranking.
- Create `scoring_rules.json` for versioned scoring weights, bands, caps, and known local requirement keys.
- Modify `src/backstage_agent/storage.py` to persist candidates, feedback, and calibration proposals.
- Modify `src/backstage_agent/agent.py` to add a candidate-first scan path while preserving compatibility fields in `ScanResult`.
- Modify `src/backstage_agent/cli.py` to expose candidate summary output and feedback/calibration commands.
- Modify `src/backstage_agent/ui.py` to add a candidate ranking view and feedback form.
- Update `PROJECT_STATE.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, and `docs/module-guide.md` for the new scoring architecture.

---

### Task 1: Candidate Domain Models And Scoring Rules

**Files:**
- Create: `src/backstage_agent/candidate_models.py`
- Create: `scoring_rules.json`
- Test: `tests/test_candidate_models.py`

**Interfaces:**
- Produces: `CandidateType`, `RequirementStatus`, `ScoreBand`, `CandidateInput`, `CandidateFeatures`, `RequirementMatch`, `CandidateScore`, `HumanFeedback`, `CalibrationProposal`.
- Consumes: existing `ProjectNotice`, `CastingNotice`, and `ActorProfile` dataclasses from `src/backstage_agent/models.py`.

- [ ] **Step 1: Write the failing model validation tests**

Add `tests/test_candidate_models.py`:

```python
import pytest

from backstage_agent.candidate_models import (
    CandidateFeatures,
    CandidateInput,
    CandidateScore,
    CandidateType,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)


def test_candidate_input_accepts_role_or_project_only(casting_notice_factory):
    role = casting_notice_factory(role="Lead")

    candidate = CandidateInput.role_candidate(
        project_id=7,
        role_id=9,
        project_key="project-key",
        role_key="role-key",
        title="Play - Lead",
        notice=role,
    )

    assert candidate.candidate_type is CandidateType.ROLE
    assert candidate.source_project_id == 7
    assert candidate.source_role_id == 9
    assert candidate.role_key == "role-key"
    assert candidate.notice is role


def test_project_only_candidate_has_no_role_id():
    candidate = CandidateInput.project_only_candidate(
        project_id=3,
        project_key="project-key",
        title="General Project Opportunity",
        source_message_id="m1",
        description="Project has no explicit parsed roles.",
        application_url="https://example.test/apply",
    )

    assert candidate.candidate_type is CandidateType.PROJECT_ONLY
    assert candidate.source_role_id is None
    assert candidate.role_key == ""
    assert candidate.notice.role == "__project_candidate__"


def test_candidate_score_clamps_to_band():
    score = CandidateScore(
        overall_score=86,
        score_band=ScoreBand.STRONG_CANDIDATE,
        subscores={"their_requirements_match": 27},
        score_caps=[],
        positive_drivers=["Explicit role fit"],
        negative_drivers=[],
        score_trace={"role_fit": {"points": 12}},
        draft_suggestion=True,
        scoring_version="2026-07-13-v1",
    )

    assert score.overall_score == 86
    assert score.score_band is ScoreBand.STRONG_CANDIDATE
    assert score.draft_suggestion is True


def test_requirement_match_status_values_are_stable():
    assert RequirementStatus.MET.value == "met"
    assert RequirementStatus.NOT_MET.value == "not_met"
    assert RequirementStatus.UNKNOWN_NEEDS_USER_INPUT.value == "unknown_needs_user_input"
    assert RequirementStatus.NOT_APPLICABLE.value == "not_applicable"


def test_candidate_features_keeps_raw_payload_for_audit():
    features = CandidateFeatures(
        role_type="scripted_acting",
        project_type="theater",
        requirements={"instagram_profile_share": {"required": True}},
        project_signals={"has_public_performance": True},
        compensation={"type": "paid"},
        uncertainty={"compensation_missing": False},
        evidence_snippets=["Requires sharing on Instagram profile."],
        raw={"model": "payload"},
    )

    assert features.requirements["instagram_profile_share"]["required"] is True
    assert features.raw == {"model": "payload"}


def test_requirement_match_records_local_fact_source():
    match = RequirementMatch(
        requirement_key="instagram_profile_share",
        status=RequirementStatus.MET,
        required=True,
        local_value="yes",
        evidence="Listing requires an Instagram profile share.",
        reason="Actor profile allows active Instagram tagging/sharing.",
        score_impact=4,
    )

    assert match.status is RequirementStatus.MET
    assert match.score_impact == 4
```

- [ ] **Step 2: Run the model tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_candidate_models.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backstage_agent.candidate_models'`.

- [ ] **Step 3: Implement candidate dataclasses and enums**

Create `src/backstage_agent/candidate_models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import CastingNotice


PROJECT_ONLY_ROLE = "__project_candidate__"


class CandidateType(str, Enum):
    ROLE = "role"
    PROJECT_ONLY = "project_only"


class RequirementStatus(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    UNKNOWN_NEEDS_USER_INPUT = "unknown_needs_user_input"
    NOT_APPLICABLE = "not_applicable"


class ScoreBand(str, Enum):
    TOP_PRIORITY = "top_priority"
    STRONG_CANDIDATE = "strong_candidate"
    MAYBE_REVIEW = "maybe_review"
    LOW_PRIORITY = "low_priority"
    NOT_WORTH_APPLYING_TODAY = "not_worth_applying_today"


@dataclass(frozen=True)
class CandidateInput:
    candidate_type: CandidateType
    title: str
    source_project_id: int
    source_role_id: int | None
    project_key: str
    role_key: str
    notice: CastingNotice

    @classmethod
    def role_candidate(
        cls,
        project_id: int,
        role_id: int,
        project_key: str,
        role_key: str,
        title: str,
        notice: CastingNotice,
    ) -> "CandidateInput":
        return cls(
            candidate_type=CandidateType.ROLE,
            title=title,
            source_project_id=project_id,
            source_role_id=role_id,
            project_key=project_key,
            role_key=role_key,
            notice=notice,
        )

    @classmethod
    def project_only_candidate(
        cls,
        project_id: int,
        project_key: str,
        title: str,
        source_message_id: str,
        description: str,
        application_url: str | None,
    ) -> "CandidateInput":
        notice = CastingNotice(
            source_message_id=source_message_id,
            title=title,
            project=title,
            role=PROJECT_ONLY_ROLE,
            location=None,
            compensation=None,
            description=description,
            application_url=application_url,
            raw_text=description,
            project_key=project_key,
            role_key="",
        )
        return cls(
            candidate_type=CandidateType.PROJECT_ONLY,
            title=title,
            source_project_id=project_id,
            source_role_id=None,
            project_key=project_key,
            role_key="",
            notice=notice,
        )


@dataclass(frozen=True)
class CandidateFeatures:
    role_type: str
    project_type: str
    requirements: dict
    project_signals: dict
    compensation: dict
    uncertainty: dict
    evidence_snippets: list[str]
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RequirementMatch:
    requirement_key: str
    status: RequirementStatus
    required: bool
    local_value: str
    evidence: str
    reason: str
    score_impact: int = 0


@dataclass(frozen=True)
class CandidateScore:
    overall_score: int
    score_band: ScoreBand
    subscores: dict[str, int]
    score_caps: list[str]
    positive_drivers: list[str]
    negative_drivers: list[str]
    score_trace: dict
    draft_suggestion: bool
    scoring_version: str
    rank_score: int | None = None
    rank_position: int | None = None


@dataclass(frozen=True)
class HumanFeedback:
    candidate_id: int
    agent_score: int
    human_score: int
    affected_components: list[str]
    failure_modes: list[str]
    free_text_reason: str
    calibration_status: str = "unreviewed_for_calibration"

    @property
    def score_delta(self) -> int:
        return self.human_score - self.agent_score


@dataclass(frozen=True)
class CalibrationProposal:
    pattern_key: str
    example_count: int
    average_delta: float
    affected_component: str
    failure_mode: str
    proposal_text: str
    status: str = "proposed"
```

- [ ] **Step 4: Add initial scoring configuration**

Create `scoring_rules.json`:

```json
{
  "version": "2026-07-13-v1",
  "component_weights": {
    "their_requirements_match": 30,
    "my_goal_alignment": 25,
    "role_value": 15,
    "project_value": 10,
    "logistics": 10,
    "compensation": 5,
    "evidence_quality": 5
  },
  "bands": [
    {"name": "top_priority", "min": 90, "max": 100},
    {"name": "strong_candidate", "min": 75, "max": 89},
    {"name": "maybe_review", "min": 60, "max": 74},
    {"name": "low_priority", "min": 40, "max": 59},
    {"name": "not_worth_applying_today", "min": 0, "max": 39}
  ],
  "score_caps": {
    "mandatory_requirement_not_met": 15,
    "hard_personal_boundary": 10,
    "expired_or_unavailable": 20,
    "missing_critical_data": 60
  },
  "draft_suggestion_min_score": 90,
  "rank_adjustment_cap": 5,
  "known_requirements": {
    "instagram_profile_share": {
      "profile_attribute": "comfortable_with_active_instagram_tagging",
      "met_values": ["true", "yes", "allowed", "comfortable"],
      "points_when_met": 4
    },
    "language_mandarin": {
      "profile_list": "skills",
      "met_values": ["mandarin", "chinese"],
      "points_when_met": 4
    },
    "union_status": {
      "profile_attribute": "union_status",
      "points_when_met": 3
    }
  }
}
```

- [ ] **Step 5: Run model tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_candidate_models.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backstage_agent/candidate_models.py scoring_rules.json tests/test_candidate_models.py
git commit -m "feat: add candidate scoring domain models"
```

---

### Task 2: Candidate Generation Without Project Filtering

**Files:**
- Create: `src/backstage_agent/candidate_generation.py`
- Test: `tests/test_candidate_generation.py`

**Interfaces:**
- Consumes: `CandidateInput` and `PROJECT_ONLY_ROLE` from `candidate_models.py`.
- Produces: `generate_candidates(project_id: int, project: ProjectNotice, stored_roles: list[tuple[int, CastingNotice]]) -> list[CandidateInput]`.

- [ ] **Step 1: Write failing candidate generation tests**

Add `tests/test_candidate_generation.py`:

```python
from backstage_agent.candidate_generation import generate_candidates
from backstage_agent.candidate_models import CandidateType, PROJECT_ONLY_ROLE
from backstage_agent.models import CastingNotice, ProjectNotice


def _project(**overrides):
    data = {
        "source_message_id": "m1",
        "title": "New Play",
        "project_url": "https://example.test/project",
        "description": "A staged reading.",
        "raw_text": "A staged reading.",
        "project_key": "new-play",
    }
    data.update(overrides)
    return ProjectNotice(**data)


def _role(**overrides):
    data = {
        "source_message_id": "m1",
        "title": "New Play - Lead",
        "project": "New Play",
        "role": "Lead",
        "location": "New York",
        "compensation": "$100",
        "description": "Lead role.",
        "application_url": "https://example.test/apply",
        "raw_text": "Lead role.",
        "project_key": "new-play",
        "role_key": "new-play-lead",
    }
    data.update(overrides)
    return CastingNotice(**data)


def test_generate_role_candidates_for_every_explicit_role():
    candidates = generate_candidates(
        project_id=11,
        project=_project(),
        stored_roles=[(21, _role(role="Lead", role_key="lead")), (22, _role(role="Friend", role_key="friend"))],
    )

    assert [candidate.candidate_type for candidate in candidates] == [
        CandidateType.ROLE,
        CandidateType.ROLE,
    ]
    assert [candidate.source_role_id for candidate in candidates] == [21, 22]
    assert [candidate.role_key for candidate in candidates] == ["lead", "friend"]


def test_generate_project_only_candidate_when_roles_are_missing():
    candidates = generate_candidates(project_id=11, project=_project(), stored_roles=[])

    assert len(candidates) == 1
    assert candidates[0].candidate_type is CandidateType.PROJECT_ONLY
    assert candidates[0].source_project_id == 11
    assert candidates[0].source_role_id is None
    assert candidates[0].notice.role == PROJECT_ONLY_ROLE


def test_generate_project_only_candidate_when_roles_are_vague():
    vague = _role(role=None, role_key="")

    candidates = generate_candidates(project_id=11, project=_project(), stored_roles=[(21, vague)])

    assert len(candidates) == 1
    assert candidates[0].candidate_type is CandidateType.PROJECT_ONLY
```

- [ ] **Step 2: Run generation tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_candidate_generation.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backstage_agent.candidate_generation'`.

- [ ] **Step 3: Implement candidate generation**

Create `src/backstage_agent/candidate_generation.py`:

```python
from __future__ import annotations

from .candidate_models import CandidateInput
from .models import CastingNotice, ProjectNotice


def generate_candidates(
    project_id: int,
    project: ProjectNotice,
    stored_roles: list[tuple[int, CastingNotice]],
) -> list[CandidateInput]:
    explicit_roles = [
        (role_id, role)
        for role_id, role in stored_roles
        if _is_explicit_role(role)
    ]
    if not explicit_roles:
        return [
            CandidateInput.project_only_candidate(
                project_id=project_id,
                project_key=project.project_key,
                title=project.title,
                source_message_id=project.source_message_id,
                description=project.description or project.raw_text,
                application_url=project.project_url,
            )
        ]
    return [
        CandidateInput.role_candidate(
            project_id=project_id,
            role_id=role_id,
            project_key=role.project_key or project.project_key,
            role_key=role.role_key,
            title=role.title,
            notice=role,
        )
        for role_id, role in explicit_roles
    ]


def _is_explicit_role(notice: CastingNotice) -> bool:
    role = (notice.role or "").strip().lower()
    return bool(role and role not in {"role", "roles", "various", "multiple roles"})
```

- [ ] **Step 4: Run generation tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_candidate_generation.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/candidate_generation.py tests/test_candidate_generation.py
git commit -m "feat: generate role and project candidates"
```

---

### Task 3: Local Requirement Matching

**Files:**
- Create: `src/backstage_agent/requirement_matcher.py`
- Test: `tests/test_requirement_matcher.py`

**Interfaces:**
- Consumes: `CandidateFeatures`, `RequirementMatch`, `RequirementStatus` from `candidate_models.py`.
- Produces: `match_requirements(features: CandidateFeatures, profile: ActorProfile, rules: dict) -> list[RequirementMatch]`.

- [ ] **Step 1: Write failing requirement matcher tests**

Add `tests/test_requirement_matcher.py`:

```python
from backstage_agent.candidate_models import CandidateFeatures, RequirementStatus
from backstage_agent.requirement_matcher import match_requirements


def _features(requirements):
    return CandidateFeatures(
        role_type="scripted_acting",
        project_type="theater",
        requirements=requirements,
        project_signals={},
        compensation={},
        uncertainty={},
        evidence_snippets=[],
    )


def _rules():
    return {
        "known_requirements": {
            "instagram_profile_share": {
                "profile_attribute": "comfortable_with_active_instagram_tagging",
                "met_values": ["true", "yes", "allowed", "comfortable"],
                "points_when_met": 4,
            },
            "language_mandarin": {
                "profile_list": "skills",
                "met_values": ["mandarin", "chinese"],
                "points_when_met": 4,
            },
        }
    }


def test_required_instagram_share_matches_profile_attribute(actor_profile_factory):
    profile = actor_profile_factory(
        attributes={"comfortable_with_active_instagram_tagging": "true"}
    )
    features = _features(
        {
            "instagram_profile_share": {
                "required": True,
                "evidence": "Must share on your Instagram profile.",
            }
        }
    )

    matches = match_requirements(features, profile, _rules())

    assert matches[0].requirement_key == "instagram_profile_share"
    assert matches[0].status is RequirementStatus.MET
    assert matches[0].score_impact == 4


def test_required_instagram_share_not_met_caps_later(actor_profile_factory):
    profile = actor_profile_factory(attributes={})
    features = _features(
        {
            "instagram_profile_share": {
                "required": True,
                "evidence": "Must share on your Instagram profile.",
            }
        }
    )

    matches = match_requirements(features, profile, _rules())

    assert matches[0].status is RequirementStatus.NOT_MET
    assert matches[0].required is True


def test_unknown_requirement_needs_user_input(actor_profile_factory):
    profile = actor_profile_factory()
    features = _features(
        {
            "can_juggle_fire": {
                "required": True,
                "evidence": "Must juggle fire.",
            }
        }
    )

    matches = match_requirements(features, profile, _rules())

    assert matches[0].requirement_key == "can_juggle_fire"
    assert matches[0].status is RequirementStatus.UNKNOWN_NEEDS_USER_INPUT


def test_language_requirement_checks_profile_skills(actor_profile_factory):
    profile = actor_profile_factory(skills=["Mandarin", "Improvisation"])
    features = _features(
        {
            "language_mandarin": {
                "required": True,
                "evidence": "Mandarin speaking role.",
            }
        }
    )

    matches = match_requirements(features, profile, _rules())

    assert matches[0].status is RequirementStatus.MET
```

- [ ] **Step 2: Run matcher tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_requirement_matcher.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backstage_agent.requirement_matcher'`.

- [ ] **Step 3: Implement requirement matcher**

Create `src/backstage_agent/requirement_matcher.py`:

```python
from __future__ import annotations

from .candidate_models import CandidateFeatures, RequirementMatch, RequirementStatus
from .models import ActorProfile


def match_requirements(
    features: CandidateFeatures,
    profile: ActorProfile,
    rules: dict,
) -> list[RequirementMatch]:
    known = rules.get("known_requirements", {})
    matches: list[RequirementMatch] = []
    for key, requirement in features.requirements.items():
        required = bool(requirement.get("required"))
        evidence = str(requirement.get("evidence") or "")
        rule = known.get(key)
        if not rule:
            matches.append(
                RequirementMatch(
                    requirement_key=key,
                    status=RequirementStatus.UNKNOWN_NEEDS_USER_INPUT,
                    required=required,
                    local_value="",
                    evidence=evidence,
                    reason="No local rule exists for this extracted requirement.",
                    score_impact=0,
                )
            )
            continue
        status, local_value = _evaluate_rule(profile, rule)
        points = int(rule.get("points_when_met", 0)) if status is RequirementStatus.MET else 0
        matches.append(
            RequirementMatch(
                requirement_key=key,
                status=status,
                required=required,
                local_value=local_value,
                evidence=evidence,
                reason=_reason_for_status(status),
                score_impact=points,
            )
        )
    return matches


def _evaluate_rule(profile: ActorProfile, rule: dict) -> tuple[RequirementStatus, str]:
    if "profile_attribute" in rule:
        attr = str(rule["profile_attribute"])
        value = profile.attributes.get(attr, "")
        if _value_matches(value, rule.get("met_values", [])):
            return RequirementStatus.MET, value
        return RequirementStatus.NOT_MET, value
    if "profile_list" in rule:
        values = getattr(profile, str(rule["profile_list"]), [])
        joined = ", ".join(str(value) for value in values)
        if any(_value_matches(value, rule.get("met_values", [])) for value in values):
            return RequirementStatus.MET, joined
        return RequirementStatus.NOT_MET, joined
    return RequirementStatus.UNKNOWN_NEEDS_USER_INPUT, ""


def _value_matches(value: str, allowed: list[str]) -> bool:
    normalized = str(value).strip().lower()
    return normalized in {str(item).strip().lower() for item in allowed}


def _reason_for_status(status: RequirementStatus) -> str:
    if status is RequirementStatus.MET:
        return "Stored actor profile satisfies this requirement."
    if status is RequirementStatus.NOT_MET:
        return "Stored actor profile does not satisfy this requirement."
    return "Requirement needs a local fact or user preference."
```

- [ ] **Step 4: Run matcher tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_requirement_matcher.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/requirement_matcher.py tests/test_requirement_matcher.py
git commit -m "feat: match candidate requirements locally"
```

---

### Task 4: Deterministic Scoring, Bands, Caps, And Re-ranking

**Files:**
- Create: `src/backstage_agent/scoring.py`
- Test: `tests/test_candidate_scoring.py`

**Interfaces:**
- Consumes: `CandidateFeatures`, `RequirementMatch`, `RequirementStatus`, `CandidateScore`, `ScoreBand`.
- Produces: `load_scoring_rules(path: Path | str = "scoring_rules.json") -> dict`, `score_candidate(features: CandidateFeatures, matches: list[RequirementMatch], rules: dict) -> CandidateScore`, `rank_candidates(scores: list[CandidateScore]) -> list[CandidateScore]`.

- [ ] **Step 1: Write failing scoring tests**

Add `tests/test_candidate_scoring.py`:

```python
from backstage_agent.candidate_models import (
    CandidateFeatures,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)
from backstage_agent.scoring import rank_candidates, score_candidate


def _features(**overrides):
    data = {
        "role_type": "scripted_acting",
        "project_type": "theater",
        "requirements": {},
        "project_signals": {"career_goal_alignment": "high", "public_performance": True},
        "compensation": {"type": "paid", "amount_known": True},
        "uncertainty": {"compensation_missing": False, "role_details_sparse": False},
        "evidence_snippets": ["Lead role in staged reading."],
    }
    data.update(overrides)
    return CandidateFeatures(**data)


def _rules():
    return {
        "version": "test-v1",
        "component_weights": {
            "their_requirements_match": 30,
            "my_goal_alignment": 25,
            "role_value": 15,
            "project_value": 10,
            "logistics": 10,
            "compensation": 5,
            "evidence_quality": 5,
        },
        "score_caps": {
            "mandatory_requirement_not_met": 15,
            "hard_personal_boundary": 10,
            "expired_or_unavailable": 20,
            "missing_critical_data": 60,
        },
        "draft_suggestion_min_score": 90,
        "rank_adjustment_cap": 5,
    }


def test_score_candidate_uses_requirement_matches_and_feature_signals():
    matches = [
        RequirementMatch(
            requirement_key="instagram_profile_share",
            status=RequirementStatus.MET,
            required=True,
            local_value="true",
            evidence="Must share on Instagram.",
            reason="Stored actor profile satisfies this requirement.",
            score_impact=4,
        )
    ]

    score = score_candidate(_features(), matches, _rules())

    assert score.overall_score >= 75
    assert score.score_band in {ScoreBand.STRONG_CANDIDATE, ScoreBand.TOP_PRIORITY}
    assert score.subscores["their_requirements_match"] == 30
    assert "instagram_profile_share" in score.score_trace


def test_mandatory_requirement_not_met_caps_score():
    matches = [
        RequirementMatch(
            requirement_key="instagram_profile_share",
            status=RequirementStatus.NOT_MET,
            required=True,
            local_value="",
            evidence="Must share on Instagram.",
            reason="Stored actor profile does not satisfy this requirement.",
            score_impact=0,
        )
    ]

    score = score_candidate(_features(), matches, _rules())

    assert score.overall_score == 15
    assert score.score_band is ScoreBand.NOT_WORTH_APPLYING_TODAY
    assert score.score_caps == ["mandatory_requirement_not_met"]


def test_missing_critical_data_caps_score_at_sixty():
    features = _features(uncertainty={"compensation_missing": True, "role_details_sparse": True})

    score = score_candidate(features, [], _rules())

    assert score.overall_score <= 60
    assert "missing_critical_data" in score.score_caps


def test_rank_candidates_applies_small_adjustments_without_overpowering_score():
    low = score_candidate(_features(project_signals={"urgent_deadline": True}), [], _rules())
    high = score_candidate(_features(project_signals={"urgent_deadline": False}), [], _rules())
    low = low.__class__(**{**low.__dict__, "overall_score": 55})
    high = high.__class__(**{**high.__dict__, "overall_score": 85})

    ranked = rank_candidates([low, high], _rules())

    assert ranked[0].overall_score == 85
    assert ranked[0].rank_position == 1
    assert ranked[1].rank_position == 2
```

- [ ] **Step 2: Run scoring tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_candidate_scoring.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backstage_agent.scoring'`.

- [ ] **Step 3: Implement deterministic scoring**

Create `src/backstage_agent/scoring.py`:

```python
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from .candidate_models import (
    CandidateFeatures,
    CandidateScore,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)


def load_scoring_rules(path: Path | str = "scoring_rules.json") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def score_candidate(
    features: CandidateFeatures,
    matches: list[RequirementMatch],
    rules: dict,
) -> CandidateScore:
    weights = rules["component_weights"]
    subscores = {
        "their_requirements_match": _requirement_score(matches, weights["their_requirements_match"]),
        "my_goal_alignment": _goal_score(features, weights["my_goal_alignment"]),
        "role_value": _role_value_score(features, weights["role_value"]),
        "project_value": _project_value_score(features, weights["project_value"]),
        "logistics": _logistics_score(features, weights["logistics"]),
        "compensation": _compensation_score(features, weights["compensation"]),
        "evidence_quality": _evidence_score(features, weights["evidence_quality"]),
    }
    raw_score = sum(subscores.values())
    caps = _score_caps(features, matches)
    capped_score = min([raw_score, *[_cap_value(cap, rules) for cap in caps]]) if caps else raw_score
    overall = max(0, min(100, int(round(capped_score))))
    return CandidateScore(
        overall_score=overall,
        score_band=_band_for_score(overall),
        subscores=subscores,
        score_caps=caps,
        positive_drivers=_positive_drivers(features, matches),
        negative_drivers=_negative_drivers(features, matches),
        score_trace=_score_trace(matches),
        draft_suggestion=overall >= int(rules.get("draft_suggestion_min_score", 90)),
        scoring_version=str(rules["version"]),
    )


def rank_candidates(scores: list[CandidateScore], rules: dict) -> list[CandidateScore]:
    cap = int(rules.get("rank_adjustment_cap", 5))
    ranked = []
    for score in scores:
        adjustment = _rank_adjustment(score, cap)
        ranked.append(replace(score, rank_score=score.overall_score + adjustment))
    ranked.sort(key=lambda item: (item.rank_score or item.overall_score, item.overall_score), reverse=True)
    return [
        replace(score, rank_position=index)
        for index, score in enumerate(ranked, start=1)
    ]


def _requirement_score(matches: list[RequirementMatch], max_points: int) -> int:
    mandatory = [match for match in matches if match.required]
    if mandatory and any(match.status is RequirementStatus.NOT_MET for match in mandatory):
        return 0
    if not mandatory:
        return max_points
    met = sum(1 for match in mandatory if match.status is RequirementStatus.MET)
    return int(round(max_points * met / len(mandatory)))


def _goal_score(features: CandidateFeatures, max_points: int) -> int:
    alignment = str(features.project_signals.get("career_goal_alignment", "")).lower()
    if alignment == "high":
        return max_points
    if alignment == "medium":
        return int(max_points * 0.65)
    if alignment == "low":
        return int(max_points * 0.3)
    return int(max_points * 0.55)


def _role_value_score(features: CandidateFeatures, max_points: int) -> int:
    if features.role_type == "scripted_acting":
        return max_points
    if features.role_type in {"voiceover", "hosting", "commercial"}:
        return int(max_points * 0.7)
    return int(max_points * 0.45)


def _project_value_score(features: CandidateFeatures, max_points: int) -> int:
    if features.project_signals.get("has_public_performance") is True:
        return max_points
    return int(max_points * 0.55)


def _logistics_score(features: CandidateFeatures, max_points: int) -> int:
    if features.uncertainty.get("schedule_conflict") is True:
        return int(max_points * 0.25)
    return int(max_points * 0.8)


def _compensation_score(features: CandidateFeatures, max_points: int) -> int:
    if features.compensation.get("type") == "paid":
        return max_points if features.compensation.get("amount_known") else int(max_points * 0.6)
    if features.compensation.get("type") == "unpaid":
        return int(max_points * 0.2)
    return int(max_points * 0.4)


def _evidence_score(features: CandidateFeatures, max_points: int) -> int:
    if len(features.evidence_snippets) >= 2:
        return max_points
    if features.evidence_snippets:
        return int(max_points * 0.8)
    return int(max_points * 0.3)


def _score_caps(features: CandidateFeatures, matches: list[RequirementMatch]) -> list[str]:
    caps = []
    if any(match.required and match.status is RequirementStatus.NOT_MET for match in matches):
        caps.append("mandatory_requirement_not_met")
    if features.project_signals.get("hard_personal_boundary") is True:
        caps.append("hard_personal_boundary")
    if features.project_signals.get("expired_or_unavailable") is True:
        caps.append("expired_or_unavailable")
    if features.uncertainty.get("compensation_missing") and features.uncertainty.get("role_details_sparse"):
        caps.append("missing_critical_data")
    return caps


def _cap_value(cap: str, rules: dict) -> int:
    return int(rules["score_caps"][cap])


def _band_for_score(score: int) -> ScoreBand:
    if score >= 90:
        return ScoreBand.TOP_PRIORITY
    if score >= 75:
        return ScoreBand.STRONG_CANDIDATE
    if score >= 60:
        return ScoreBand.MAYBE_REVIEW
    if score >= 40:
        return ScoreBand.LOW_PRIORITY
    return ScoreBand.NOT_WORTH_APPLYING_TODAY


def _positive_drivers(features: CandidateFeatures, matches: list[RequirementMatch]) -> list[str]:
    drivers = []
    if features.role_type == "scripted_acting":
        drivers.append("Explicit scripted acting role")
    for match in matches:
        if match.status is RequirementStatus.MET:
            drivers.append(f"{match.requirement_key} requirement met")
    return drivers


def _negative_drivers(features: CandidateFeatures, matches: list[RequirementMatch]) -> list[str]:
    drivers = []
    for match in matches:
        if match.status is RequirementStatus.NOT_MET:
            drivers.append(f"{match.requirement_key} requirement not met")
        elif match.status is RequirementStatus.UNKNOWN_NEEDS_USER_INPUT:
            drivers.append(f"{match.requirement_key} needs user input")
    if features.uncertainty.get("compensation_missing"):
        drivers.append("Compensation details missing")
    if features.uncertainty.get("role_details_sparse"):
        drivers.append("Role details sparse")
    return drivers


def _score_trace(matches: list[RequirementMatch]) -> dict:
    return {
        match.requirement_key: {
            "status": match.status.value,
            "points": match.score_impact,
            "evidence": match.evidence,
            "reason": match.reason,
        }
        for match in matches
    }


def _rank_adjustment(score: CandidateScore, cap: int) -> int:
    adjustment = 0
    if score.score_trace.get("urgent_deadline"):
        adjustment += 3
    if "missing_critical_data" in score.score_caps:
        adjustment -= 3
    return max(-cap, min(cap, adjustment))
```

- [ ] **Step 4: Run scoring tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_candidate_scoring.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/scoring.py tests/test_candidate_scoring.py
git commit -m "feat: score and rank candidates deterministically"
```

---

### Task 5: LLM Feature Extraction Schema

**Files:**
- Create: `src/backstage_agent/feature_extractor.py`
- Test: `tests/test_feature_extractor.py`

**Interfaces:**
- Consumes: `CandidateInput` and `CandidateFeatures`.
- Produces: `FeatureExtractor.extract(candidate: CandidateInput) -> CandidateFeatures`.

- [ ] **Step 1: Write failing extractor tests**

Add `tests/test_feature_extractor.py`:

```python
from backstage_agent.candidate_models import CandidateInput
from backstage_agent.feature_extractor import FeatureExtractor


def test_feature_extractor_returns_features_without_scores(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
    payload = {
        "role_type": "scripted_acting",
        "project_type": "theater",
        "requirements": {
            "instagram_profile_share": {
                "required": True,
                "evidence": "Must share on Instagram profile.",
            }
        },
        "project_signals": {"career_goal_alignment": "high", "has_public_performance": True},
        "compensation": {"type": "paid", "amount_known": False},
        "uncertainty": {"compensation_missing": True, "role_details_sparse": False},
        "evidence_snippets": ["Must share on Instagram profile."],
    }
    extractor = FeatureExtractor(settings_factory(), actor_profile_factory())
    extractor._client = fake_chat_client_factory([payload])
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )

    features = extractor.extract(candidate)

    assert features.role_type == "scripted_acting"
    assert features.requirements["instagram_profile_share"]["required"] is True
    assert "overall_score" not in features.raw
    assert "score_band" not in features.raw
    assert "should_apply" not in features.raw


def test_feature_extractor_rejects_score_fields(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
    payload = {
        "role_type": "scripted_acting",
        "project_type": "theater",
        "requirements": {},
        "project_signals": {},
        "compensation": {},
        "uncertainty": {},
        "evidence_snippets": [],
        "overall_score": 99,
    }
    extractor = FeatureExtractor(settings_factory(), actor_profile_factory())
    extractor._client = fake_chat_client_factory([payload])
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )

    features = extractor.extract(candidate)

    assert features.raw["schema_warning"] == "removed disallowed scoring fields"
    assert "overall_score" not in features.raw
```

- [ ] **Step 2: Run extractor tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_feature_extractor.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backstage_agent.feature_extractor'`.

- [ ] **Step 3: Implement feature extractor**

Create `src/backstage_agent/feature_extractor.py`:

```python
from __future__ import annotations

import json

from .candidate_models import CandidateFeatures, CandidateInput
from .llm_client import make_chat_client
from .models import ActorProfile
from .settings import Settings


DISALLOWED_SCORE_FIELDS = {"overall_score", "score_band", "should_apply", "draft_suggestion"}


class FeatureExtractor:
    def __init__(self, settings: Settings, profile: ActorProfile):
        self.settings = settings
        self.profile = profile
        self._client = make_chat_client(settings)

    def extract(self, candidate: CandidateInput) -> CandidateFeatures:
        data = self._request_features(candidate)
        clean, removed = _remove_score_fields(data)
        features = CandidateFeatures(
            role_type=str(clean["role_type"]),
            project_type=str(clean["project_type"]),
            requirements=dict(clean["requirements"]),
            project_signals=dict(clean["project_signals"]),
            compensation=dict(clean["compensation"]),
            uncertainty=dict(clean["uncertainty"]),
            evidence_snippets=[str(item) for item in clean["evidence_snippets"]],
            raw=dict(clean),
        )
        if removed:
            features.raw["schema_warning"] = "removed disallowed scoring fields"
        return features

    def _request_features(self, candidate: CandidateInput) -> dict:
        response = self._client.chat.completions.create(
            model=self.settings.llm_model,
            messages=[
                {"role": "system", "content": _FEATURE_EXTRACTION_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "candidate_type": candidate.candidate_type.value,
                            "title": candidate.title,
                            "notice": candidate.notice.__dict__,
                            "profile_summary": {
                                "location": self.profile.location,
                                "age_range": self.profile.age_range,
                                "genders": self.profile.genders,
                                "ethnicities": self.profile.ethnicities,
                                "union_status": self.profile.union_status,
                                "skills": self.profile.skills,
                                "avoid": self.profile.avoid,
                                "preferred_roles": self.profile.preferred_roles,
                                "attributes": self.profile.attributes,
                            },
                        },
                        default=str,
                    ),
                },
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)


def _remove_score_fields(data: dict) -> tuple[dict, bool]:
    clean = dict(data)
    removed = False
    for field in DISALLOWED_SCORE_FIELDS:
        if field in clean:
            clean.pop(field)
            removed = True
    _validate_required_fields(clean)
    return clean, removed


def _validate_required_fields(data: dict) -> None:
    required = {
        "role_type",
        "project_type",
        "requirements",
        "project_signals",
        "compensation",
        "uncertainty",
        "evidence_snippets",
    }
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError("missing feature extraction fields: " + ", ".join(missing))


_FEATURE_EXTRACTION_PROMPT = (
    "Extract structured casting candidate features as JSON. Do not score, rank, "
    "recommend applying, or decide whether the actor should apply. Return only "
    "role_type, project_type, requirements, project_signals, compensation, "
    "uncertainty, and evidence_snippets. Every important extracted requirement "
    "must include evidence from the notice."
)
```

- [ ] **Step 4: Run extractor tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_feature_extractor.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/feature_extractor.py tests/test_feature_extractor.py
git commit -m "feat: extract candidate features without scores"
```

---

### Task 6: Candidate Persistence, Search, Feedback, And Proposals

**Files:**
- Modify: `src/backstage_agent/storage.py`
- Test: `tests/test_candidate_storage.py`

**Interfaces:**
- Consumes: `CandidateInput`, `CandidateFeatures`, `RequirementMatch`, `CandidateScore`, `HumanFeedback`, `CalibrationProposal`.
- Produces: `DecisionStore.record_candidate(...) -> int`, `DecisionStore.search_candidates(...) -> list[sqlite3.Row]`, `DecisionStore.record_candidate_feedback(feedback: HumanFeedback) -> int`, `DecisionStore.feedback_patterns(min_examples: int = 2) -> list[sqlite3.Row]`, `DecisionStore.record_calibration_proposal(proposal: CalibrationProposal) -> int`.

- [ ] **Step 1: Write failing storage tests**

Add `tests/test_candidate_storage.py`:

```python
import json

from backstage_agent.candidate_models import (
    CandidateFeatures,
    CandidateInput,
    CandidateScore,
    HumanFeedback,
    RequirementMatch,
    RequirementStatus,
    ScoreBand,
)
from backstage_agent.storage import DecisionStore


def _features():
    return CandidateFeatures(
        role_type="scripted_acting",
        project_type="theater",
        requirements={},
        project_signals={},
        compensation={},
        uncertainty={},
        evidence_snippets=["Evidence"],
    )


def _match():
    return RequirementMatch(
        requirement_key="instagram_profile_share",
        status=RequirementStatus.MET,
        required=True,
        local_value="true",
        evidence="Must share.",
        reason="Stored fact matches.",
        score_impact=4,
    )


def _score():
    return CandidateScore(
        overall_score=86,
        score_band=ScoreBand.STRONG_CANDIDATE,
        subscores={"their_requirements_match": 30},
        score_caps=[],
        positive_drivers=["Good fit"],
        negative_drivers=[],
        score_trace={"instagram_profile_share": {"points": 4}},
        draft_suggestion=False,
        scoring_version="test-v1",
        rank_score=87,
        rank_position=1,
    )


def test_record_and_search_candidate(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )

    candidate_id = store.record_candidate(candidate, _features(), [_match()], _score())
    rows = store.search_candidates()

    assert candidate_id == rows[0]["id"]
    assert rows[0]["overall_score"] == 86
    assert rows[0]["score_band"] == "strong_candidate"
    assert json.loads(rows[0]["features_json"])["role_type"] == "scripted_acting"
    assert json.loads(rows[0]["requirement_match_json"])[0]["requirement_key"] == "instagram_profile_share"


def test_feedback_patterns_group_taxonomy(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )
    candidate_id = store.record_candidate(candidate, _features(), [_match()], _score())

    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=86,
            human_score=45,
            affected_components=["identity_match"],
            failure_modes=["overweighted_signal"],
            free_text_reason="Nationality over-weighted.",
        )
    )
    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id,
            agent_score=80,
            human_score=50,
            affected_components=["identity_match"],
            failure_modes=["overweighted_signal"],
            free_text_reason="Same issue.",
        )
    )

    patterns = store.feedback_patterns(min_examples=2)

    assert patterns[0]["affected_component"] == "identity_match"
    assert patterns[0]["failure_mode"] == "overweighted_signal"
    assert patterns[0]["example_count"] == 2
    assert patterns[0]["average_delta"] < 0
```

- [ ] **Step 2: Run storage tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_candidate_storage.py -v
```

Expected: FAIL with `AttributeError: 'DecisionStore' object has no attribute 'record_candidate'`.

- [ ] **Step 3: Add candidate tables and migrations**

Modify `DecisionStore._ensure_schema()` in `src/backstage_agent/storage.py` by adding these tables to the existing `conn.executescript(...)` block:

```python
                CREATE TABLE IF NOT EXISTS candidates (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  candidate_type TEXT NOT NULL,
                  title TEXT NOT NULL,
                  source_project_id INTEGER NOT NULL,
                  source_role_id INTEGER,
                  project_key TEXT,
                  role_key TEXT,
                  notice_json TEXT NOT NULL,
                  features_json TEXT NOT NULL,
                  requirement_match_json TEXT NOT NULL,
                  score_json TEXT NOT NULL,
                  overall_score INTEGER NOT NULL,
                  score_band TEXT NOT NULL,
                  rank_score INTEGER,
                  rank_position INTEGER,
                  draft_suggestion INTEGER NOT NULL,
                  scoring_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidate_feedback (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  candidate_id INTEGER NOT NULL,
                  agent_score INTEGER NOT NULL,
                  human_score INTEGER NOT NULL,
                  score_delta INTEGER NOT NULL,
                  affected_components_json TEXT NOT NULL,
                  failure_modes_json TEXT NOT NULL,
                  free_text_reason TEXT NOT NULL,
                  calibration_status TEXT NOT NULL,
                  FOREIGN KEY(candidate_id) REFERENCES candidates(id)
                );
                CREATE TABLE IF NOT EXISTS calibration_proposals (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  pattern_key TEXT NOT NULL,
                  example_count INTEGER NOT NULL,
                  average_delta REAL NOT NULL,
                  affected_component TEXT NOT NULL,
                  failure_mode TEXT NOT NULL,
                  proposal_text TEXT NOT NULL,
                  status TEXT NOT NULL
                );
```

Add indexes after existing index creation:

```python
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates(overall_score)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_band ON candidates(score_band)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_candidate_feedback_candidate ON candidate_feedback(candidate_id)")
```

- [ ] **Step 4: Add candidate persistence methods**

Add imports at the top of `src/backstage_agent/storage.py`:

```python
from .candidate_models import (
    CalibrationProposal,
    CandidateFeatures,
    CandidateInput,
    CandidateScore,
    HumanFeedback,
    RequirementMatch,
)
```

Add these methods to `DecisionStore` before `_connect()`:

```python
    def record_candidate(
        self,
        candidate: CandidateInput,
        features: CandidateFeatures,
        requirement_matches: list[RequirementMatch],
        score: CandidateScore,
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO candidates (
                  candidate_type, title, source_project_id, source_role_id,
                  project_key, role_key, notice_json, features_json,
                  requirement_match_json, score_json, overall_score, score_band,
                  rank_score, rank_position, draft_suggestion, scoring_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate.candidate_type.value,
                    candidate.title,
                    candidate.source_project_id,
                    candidate.source_role_id,
                    candidate.project_key,
                    candidate.role_key,
                    json.dumps(candidate.notice.__dict__, default=str),
                    json.dumps(features.__dict__, default=str),
                    json.dumps([match.__dict__ | {"status": match.status.value} for match in requirement_matches]),
                    json.dumps(score.__dict__ | {"score_band": score.score_band.value}, default=str),
                    score.overall_score,
                    score.score_band.value,
                    score.rank_score,
                    score.rank_position,
                    int(score.draft_suggestion),
                    score.scoring_version,
                ),
            )
            return int(cursor.lastrowid)

    def search_candidates(
        self,
        query: str = "",
        band: str = "all",
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[object] = []
        if query:
            clauses.append("(lower(title) LIKE lower(?) OR lower(notice_json) LIKE lower(?))")
            params.extend([f"%{query}%", f"%{query}%"])
        if band != "all":
            clauses.append("score_band = ?")
            params.append(band)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    f"""
                    SELECT *
                    FROM candidates
                    {where}
                    ORDER BY COALESCE(rank_position, 999999), overall_score DESC, id DESC
                    LIMIT ?
                    """,
                    params,
                )
            )

    def record_candidate_feedback(self, feedback: HumanFeedback) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO candidate_feedback (
                  candidate_id, agent_score, human_score, score_delta,
                  affected_components_json, failure_modes_json,
                  free_text_reason, calibration_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    feedback.candidate_id,
                    feedback.agent_score,
                    feedback.human_score,
                    feedback.score_delta,
                    json.dumps(feedback.affected_components),
                    json.dumps(feedback.failure_modes),
                    feedback.free_text_reason,
                    feedback.calibration_status,
                ),
            )
            return int(cursor.lastrowid)

    def feedback_patterns(self, min_examples: int = 2) -> list[sqlite3.Row]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            return list(
                conn.execute(
                    """
                    SELECT
                      json_extract(affected_components_json, '$[0]') AS affected_component,
                      json_extract(failure_modes_json, '$[0]') AS failure_mode,
                      COUNT(*) AS example_count,
                      AVG(score_delta) AS average_delta
                    FROM candidate_feedback
                    GROUP BY affected_component, failure_mode
                    HAVING COUNT(*) >= ?
                    ORDER BY ABS(AVG(score_delta)) DESC, COUNT(*) DESC
                    """,
                    (min_examples,),
                )
            )

    def record_calibration_proposal(self, proposal: CalibrationProposal) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO calibration_proposals (
                  pattern_key, example_count, average_delta, affected_component,
                  failure_mode, proposal_text, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.pattern_key,
                    proposal.example_count,
                    proposal.average_delta,
                    proposal.affected_component,
                    proposal.failure_mode,
                    proposal.proposal_text,
                    proposal.status,
                ),
            )
            return int(cursor.lastrowid)
```

- [ ] **Step 5: Run storage tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_candidate_storage.py -v
```

Expected: PASS.

- [ ] **Step 6: Run existing storage dashboard tests**

Run:

```bash
python3 -m pytest tests/test_storage_dashboard.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/backstage_agent/storage.py tests/test_candidate_storage.py
git commit -m "feat: persist scored candidates and feedback"
```

---

### Task 7: Candidate-First Agent Orchestration

**Files:**
- Modify: `src/backstage_agent/agent.py`
- Test: `tests/test_agent_candidate_scoring.py`

**Interfaces:**
- Consumes: `generate_candidates`, `FeatureExtractor`, `match_requirements`, `score_candidate`, `rank_candidates`, and `DecisionStore.record_candidate`.
- Produces: `ScanResult.candidates_scored: int`, `ScanResult.draft_suggestions: int`, and candidate records in storage for every generated candidate.

- [ ] **Step 1: Write failing agent orchestration test**

Add `tests/test_agent_candidate_scoring.py`:

```python
from backstage_agent.agent import BackstageAgent
from backstage_agent.candidate_models import CandidateFeatures
from backstage_agent.models import EmailMessage, ProjectNotice


class FakeEmailClient:
    def fetch_messages(self, limit, days=1, target_date=None):
        return [EmailMessage("m1", "Backstage", "sender", None, "", "text")]


class FakeProjectPages:
    def fetch_html(self, url):
        return ""


class FakeFeatureExtractor:
    def extract(self, candidate):
        return CandidateFeatures(
            role_type="scripted_acting",
            project_type="theater",
            requirements={},
            project_signals={"career_goal_alignment": "high", "has_public_performance": True},
            compensation={"type": "paid", "amount_known": True},
            uncertainty={"compensation_missing": False, "role_details_sparse": False},
            evidence_snippets=["Evidence"],
        )


def test_scan_scores_project_only_candidate_when_roles_missing(monkeypatch, settings_factory, tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(
        '{"name":"Actor","location":"LA","age_range":"25-45","genders":["female"],'
        '"ethnicities":["open"],"union_status":"non-union","skills":[],"avoid":[],'
        '"preferred_roles":[],"max_travel_miles":35,"cover_note_template":"Hello",'
        '"attributes":{"comfortable_with_active_instagram_tagging":"true"}}',
        encoding="utf-8",
    )
    settings = settings_factory(actor_profile_path=profile_path)

    monkeypatch.setattr(
        "backstage_agent.agent.parse_project_notices",
        lambda message: [
            ProjectNotice(
                source_message_id="m1",
                title="Project With No Roles",
                project_url=None,
                description="General opportunity.",
                raw_text="General opportunity.",
                project_key="project-with-no-roles",
            )
        ],
    )
    monkeypatch.setattr("backstage_agent.agent.parse_project_page_roles", lambda project, html: [])

    agent = BackstageAgent(settings)
    agent.email_client = FakeEmailClient()
    agent.project_pages = FakeProjectPages()
    agent.feature_extractor = FakeFeatureExtractor()

    result = agent.scan(limit=1)
    candidates = agent.store.search_candidates()

    assert result.candidates_scored == 1
    assert candidates[0]["candidate_type"] == "project_only"
    assert candidates[0]["overall_score"] > 0
```

- [ ] **Step 2: Run agent candidate test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_agent_candidate_scoring.py -v
```

Expected: FAIL with `AttributeError: 'BackstageAgent' object has no attribute 'feature_extractor'` or missing `ScanResult.candidates_scored`.

- [ ] **Step 3: Wire candidate services into agent initialization**

Modify imports in `src/backstage_agent/agent.py`:

```python
from .candidate_generation import generate_candidates
from .feature_extractor import FeatureExtractor
from .requirement_matcher import match_requirements
from .scoring import load_scoring_rules, rank_candidates, score_candidate
```

Modify `ScanResult`:

```python
@dataclass(frozen=True)
class ScanResult:
    messages_seen: int
    projects_seen: int
    notices_seen: int
    project_decisions: list[ScreeningDecision]
    project_reviews: list[ReviewDecision]
    decisions: list[ScreeningDecision]
    reviews: list[ReviewDecision]
    applications: list[ApplicationDraft]
    candidates_scored: int = 0
    draft_suggestions: int = 0
```

Modify `BackstageAgent.__init__`:

```python
        self.feature_extractor = FeatureExtractor(settings, self.profile)
        self.scoring_rules = load_scoring_rules()
```

- [ ] **Step 4: Generate, score, rank, and persist candidates inside scan**

Inside `BackstageAgent.scan`, add local accumulator after `application_drafts`:

```python
        candidate_records = []
```

Inside the project loop, replace the current project-gate `continue` behavior with candidate generation. Keep existing decision recording as a temporary compatibility path, but do not let project review block candidate generation. After page roles are parsed and stored, collect stored role IDs:

```python
                stored_roles: list[tuple[int, object]] = []
                for role in page_roles:
                    if self.store.role_exists(role.role_key) or self.store.decision_exists(role.role_key):
                        continue
                    role_id = self.store.record_role(project_id, role)
                    stored_roles.append((role_id, role))
                    notices.append(role)
                generated = generate_candidates(project_id, project, stored_roles)
                scored_for_project = []
                for candidate in generated:
                    features = self.feature_extractor.extract(candidate)
                    requirement_matches = match_requirements(
                        features,
                        self.profile,
                        self.scoring_rules,
                    )
                    score = score_candidate(features, requirement_matches, self.scoring_rules)
                    scored_for_project.append((candidate, features, requirement_matches, score))
                ranked_scores = rank_candidates(
                    [item[3] for item in scored_for_project],
                    self.scoring_rules,
                )
                for (candidate, features, requirement_matches, _score), ranked_score in zip(
                    scored_for_project,
                    ranked_scores,
                    strict=True,
                ):
                    self.store.record_candidate(
                        candidate,
                        features,
                        requirement_matches,
                        ranked_score,
                    )
                    candidate_records.append(ranked_score)
```

Keep the old project/role decision flow in place for this task except remove any `continue` that prevents candidates from being generated. If the old flow still skips application drafting, that is acceptable because drafting is now explicitly downstream.

Update the return:

```python
            candidates_scored=len(candidate_records),
            draft_suggestions=sum(1 for score in candidate_records if score.draft_suggestion),
```

- [ ] **Step 5: Run agent candidate test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_agent_candidate_scoring.py -v
```

Expected: PASS.

- [ ] **Step 6: Run review gate regression tests**

Run:

```bash
python3 -m pytest tests/test_agent_review_gate.py -v
```

Expected: PASS. If this fails because the test expects project review to block role processing, update that assertion only where it conflicts with the approved candidate-first design: project review may no longer block candidate scoring, but should still block legacy auto-drafting.

- [ ] **Step 7: Commit**

```bash
git add src/backstage_agent/agent.py tests/test_agent_candidate_scoring.py tests/test_agent_review_gate.py
git commit -m "feat: score candidates during scans"
```

---

### Task 8: Candidate CLI Summary And Feedback Commands

**Files:**
- Modify: `src/backstage_agent/cli.py`
- Test: `tests/test_cli_candidates.py`

**Interfaces:**
- Consumes: `DecisionStore.search_candidates`, `DecisionStore.record_candidate_feedback`, `DecisionStore.feedback_patterns`.
- Produces: CLI commands `candidates`, `candidate-feedback`, and `calibration-patterns`.

- [ ] **Step 1: Write failing CLI tests**

Add `tests/test_cli_candidates.py`:

```python
import json

from backstage_agent.cli import _candidate_rows_json, _record_feedback_from_args
from backstage_agent.candidate_models import HumanFeedback


class FakeStore:
    def __init__(self):
        self.feedback = None

    def search_candidates(self, query="", band="all", limit=200):
        return [
            {
                "id": 1,
                "title": "Play - Lead",
                "overall_score": 86,
                "score_band": "strong_candidate",
                "draft_suggestion": 1,
                "rank_position": 1,
            }
        ]

    def record_candidate_feedback(self, feedback: HumanFeedback):
        self.feedback = feedback
        return 9


def test_candidate_rows_json_outputs_ranked_candidates():
    payload = json.loads(_candidate_rows_json(FakeStore(), limit=10))

    assert payload[0]["title"] == "Play - Lead"
    assert payload[0]["overall_score"] == 86
    assert payload[0]["draft_suggestion"] is True


def test_record_feedback_from_args_stores_taxonomy():
    class Args:
        candidate_id = 1
        agent_score = 86
        human_score = 45
        affected_components = "identity_match"
        failure_modes = "overweighted_signal"
        reason = "Nationality over-weighted."

    store = FakeStore()
    feedback_id = _record_feedback_from_args(store, Args())

    assert feedback_id == 9
    assert store.feedback.score_delta == -41
    assert store.feedback.affected_components == ["identity_match"]
```

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_cli_candidates.py -v
```

Expected: FAIL with missing helper imports.

- [ ] **Step 3: Add candidate CLI commands**

Modify imports in `src/backstage_agent/cli.py`:

```python
from .candidate_models import HumanFeedback
```

Add subparsers in `main()`:

```python
    candidates_parser = subparsers.add_parser("candidates", help="Show ranked scored candidates")
    candidates_parser.add_argument("--limit", type=int, default=50)
    candidates_parser.add_argument("--band", default="all")
    candidates_parser.add_argument("--q", default="")

    feedback_parser = subparsers.add_parser("candidate-feedback", help="Record human scoring feedback")
    feedback_parser.add_argument("candidate_id", type=int)
    feedback_parser.add_argument("--agent-score", type=int, required=True)
    feedback_parser.add_argument("--human-score", type=int, required=True)
    feedback_parser.add_argument("--affected-components", required=True)
    feedback_parser.add_argument("--failure-modes", required=True)
    feedback_parser.add_argument("--reason", required=True)

    subparsers.add_parser("calibration-patterns", help="Show grouped feedback patterns")
```

Add command dispatch:

```python
    elif args.command == "candidates":
        _candidates(args.limit, args.band, args.q)
    elif args.command == "candidate-feedback":
        settings = load_settings()
        feedback_id = _record_feedback_from_args(DecisionStore(settings.database_path), args)
        print(json.dumps({"feedback_id": feedback_id}, indent=2))
    elif args.command == "calibration-patterns":
        _calibration_patterns()
```

Add helpers:

```python
def _candidates(limit: int, band: str, query: str) -> None:
    settings = load_settings()
    print(_candidate_rows_json(DecisionStore(settings.database_path), limit=limit, band=band, query=query))


def _candidate_rows_json(store: DecisionStore, limit: int = 50, band: str = "all", query: str = "") -> str:
    rows = store.search_candidates(query=query, band=band, limit=limit)
    return json.dumps(
        [
            {
                "id": row["id"],
                "rank_position": row["rank_position"],
                "title": row["title"],
                "overall_score": row["overall_score"],
                "score_band": row["score_band"],
                "draft_suggestion": bool(row["draft_suggestion"]),
            }
            for row in rows
        ],
        indent=2,
    )


def _record_feedback_from_args(store: DecisionStore, args) -> int:
    feedback = HumanFeedback(
        candidate_id=args.candidate_id,
        agent_score=args.agent_score,
        human_score=args.human_score,
        affected_components=_csv(args.affected_components),
        failure_modes=_csv(args.failure_modes),
        free_text_reason=args.reason,
    )
    return store.record_candidate_feedback(feedback)


def _calibration_patterns() -> None:
    settings = load_settings()
    rows = DecisionStore(settings.database_path).feedback_patterns()
    print(
        json.dumps(
            [
                {
                    "affected_component": row["affected_component"],
                    "failure_mode": row["failure_mode"],
                    "example_count": row["example_count"],
                    "average_delta": row["average_delta"],
                }
                for row in rows
            ],
            indent=2,
        )
    )


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
```

Update `_scan` JSON output to include:

```python
                "candidates_scored": result.candidates_scored,
                "draft_suggestions": result.draft_suggestions,
```

Update `_scan_summary` to append:

```python
    if result.candidates_scored:
        summary = (
            f"{summary} Candidates: {result.candidates_scored} scored, "
            f"{result.draft_suggestions} draft suggestions."
        )
```

- [ ] **Step 4: Run CLI tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_cli_candidates.py tests/test_cli_summary.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/cli.py tests/test_cli_candidates.py tests/test_cli_summary.py
git commit -m "feat: add candidate CLI and feedback commands"
```

---

### Task 9: Dashboard Candidate Ranking View And Feedback Form

**Files:**
- Modify: `src/backstage_agent/ui.py`
- Test: `tests/test_ui_candidates.py`

**Interfaces:**
- Consumes: `DecisionStore.search_candidates` and candidate row fields.
- Produces: dashboard route `/candidates` rendering ranked scored candidates and a feedback form target `/candidate-feedback`.

- [ ] **Step 1: Write failing UI rendering tests**

Add `tests/test_ui_candidates.py`:

```python
from backstage_agent.ui import _render_candidates_index


class FakeStore:
    def search_candidates(self, query="", band="all", limit=200):
        return [
            {
                "id": 1,
                "title": "Play - Lead",
                "overall_score": 86,
                "score_band": "strong_candidate",
                "rank_position": 1,
                "draft_suggestion": 1,
                "positive_drivers": None,
                "score_json": '{"positive_drivers":["Explicit role fit"],"negative_drivers":["Compensation unknown"],"subscores":{"their_requirements_match":30}}',
                "features_json": '{"role_type":"scripted_acting"}',
                "requirement_match_json": "[]",
            }
        ]


def test_render_candidates_index_shows_ranked_score_and_feedback_form():
    html = _render_candidates_index(FakeStore(), {})

    assert "Backstage Candidates" in html
    assert "Play - Lead" in html
    assert "86" in html
    assert "strong_candidate" in html
    assert "candidate-feedback" in html
    assert "Human score" in html
```

- [ ] **Step 2: Run UI tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_ui_candidates.py -v
```

Expected: FAIL with missing `_render_candidates_index`.

- [ ] **Step 3: Add `/candidates` route**

Modify `DashboardServer.serve_forever()` handler in `src/backstage_agent/ui.py`:

```python
                if parsed.path == "/candidates":
                    self._send_html(_render_candidates_index(store, parse_qs(parsed.query)))
                    return
```

- [ ] **Step 4: Add candidate rendering helpers**

Add to `src/backstage_agent/ui.py`:

```python
def _render_candidates_index(store: DecisionStore, params: dict[str, list[str]]) -> str:
    query = _param(params, "q")
    band = _param(params, "band", "all")
    rows = store.search_candidates(query=query, band=band, limit=200)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Backstage Candidates</title>
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>Backstage Candidates</h1>
      <p>Ranked mutual-selection scores</p>
    </div>
    <a class="button" href="/">Decisions</a>
  </header>
  <main>
    <form class="filters" method="get" action="/candidates">
      <label>Search<input name="q" value="{_esc(query)}" placeholder="Title, score reason, notice text"></label>
      <label>Band<input name="band" value="{_esc(band)}" placeholder="all"></label>
      <button type="submit">Search</button>
    </form>
    <section class="list">
      {_render_candidate_rows(rows)}
    </section>
  </main>
</body>
</html>"""


def _render_candidate_rows(rows) -> str:
    if not rows:
        return '<div class="empty">No candidates match the current filters.</div>'
    return "\n".join(_render_candidate_row(row) for row in rows)


def _render_candidate_row(row) -> str:
    score = json.loads(row["score_json"])
    positives = score.get("positive_drivers", [])
    negatives = score.get("negative_drivers", [])
    return f"""
    <article class="row">
      <div class="row-top">
        <div class="row-labels">
          <span class="pill ok">{_esc(row["score_band"])}</span>
          {_draft_chip(row)}
        </div>
        <span class="score">{int(row["overall_score"])}</span>
      </div>
      <strong>#{_esc(row["rank_position"] or "")} {_esc(row["title"])}</strong>
      <h3>Positive Drivers</h3>
      {_list(positives)}
      <h3>Negative Drivers</h3>
      {_list(negatives) if negatives else '<p class="muted">None recorded.</p>'}
      <form class="feedback" method="post" action="/candidate-feedback">
        <input type="hidden" name="candidate_id" value="{_esc(row["id"])}">
        <label>Human score<input name="human_score" type="number" min="0" max="100"></label>
        <label>Affected component<input name="affected_components" placeholder="identity_match"></label>
        <label>Failure mode<input name="failure_modes" placeholder="overweighted_signal"></label>
        <label>Reason<input name="reason" placeholder="Nationality over-weighted."></label>
      </form>
    </article>
    """


def _draft_chip(row) -> str:
    if row["draft_suggestion"]:
        return '<span class="pill hold">Draft suggested</span>'
    return '<span class="pill muted-pill">No draft suggestion</span>'
```

Do not implement POST handling in this task; the form is a visual affordance. CLI feedback is the functional path from Task 8.

- [ ] **Step 5: Run UI tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_ui_candidates.py tests/test_ui_labels.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backstage_agent/ui.py tests/test_ui_candidates.py
git commit -m "feat: show ranked candidates in dashboard"
```

---

### Task 10: Calibration Proposal Generation

**Files:**
- Create: `src/backstage_agent/calibration.py`
- Modify: `src/backstage_agent/cli.py`
- Test: `tests/test_calibration.py`

**Interfaces:**
- Consumes: feedback pattern rows from `DecisionStore.feedback_patterns`.
- Produces: `build_calibration_proposals(patterns: list) -> list[CalibrationProposal]` and CLI output for proposed scoring changes.

- [ ] **Step 1: Write failing calibration tests**

Add `tests/test_calibration.py`:

```python
from backstage_agent.calibration import build_calibration_proposals


def test_build_calibration_proposal_for_overweighted_identity_signal():
    patterns = [
        {
            "affected_component": "identity_match",
            "failure_mode": "overweighted_signal",
            "example_count": 4,
            "average_delta": -28.0,
        }
    ]

    proposals = build_calibration_proposals(patterns)

    assert proposals[0].pattern_key == "identity_match:overweighted_signal"
    assert proposals[0].example_count == 4
    assert "reduce" in proposals[0].proposal_text.lower()
    assert "identity" in proposals[0].proposal_text.lower()
```

- [ ] **Step 2: Run calibration tests to verify they fail**

Run:

```bash
python3 -m pytest tests/test_calibration.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'backstage_agent.calibration'`.

- [ ] **Step 3: Implement calibration proposal builder**

Create `src/backstage_agent/calibration.py`:

```python
from __future__ import annotations

from .candidate_models import CalibrationProposal


def build_calibration_proposals(patterns: list) -> list[CalibrationProposal]:
    proposals = []
    for row in patterns:
        affected_component = str(row["affected_component"])
        failure_mode = str(row["failure_mode"])
        proposals.append(
            CalibrationProposal(
                pattern_key=f"{affected_component}:{failure_mode}",
                example_count=int(row["example_count"]),
                average_delta=float(row["average_delta"]),
                affected_component=affected_component,
                failure_mode=failure_mode,
                proposal_text=_proposal_text(affected_component, failure_mode, float(row["average_delta"])),
            )
        )
    return proposals


def _proposal_text(component: str, failure_mode: str, average_delta: float) -> str:
    direction = "reduce" if average_delta < 0 else "increase"
    if component == "identity_match" and failure_mode == "overweighted_signal":
        return (
            "Proposal: reduce contextual identity-match points and award full "
            "identity-match credit only when the listing states a requirement."
        )
    if failure_mode == "overweighted_signal":
        return f"Proposal: reduce the scoring weight or cap contribution for {component}."
    if failure_mode == "underweighted_signal":
        return f"Proposal: increase the scoring weight for {component}."
    return f"Proposal: review {component} scoring because feedback suggests a {direction} adjustment."
```

- [ ] **Step 4: Wire proposals into CLI**

Modify imports in `src/backstage_agent/cli.py`:

```python
from .calibration import build_calibration_proposals
```

Modify `_calibration_patterns()`:

```python
def _calibration_patterns() -> None:
    settings = load_settings()
    store = DecisionStore(settings.database_path)
    patterns = store.feedback_patterns()
    proposals = build_calibration_proposals(patterns)
    for proposal in proposals:
        store.record_calibration_proposal(proposal)
    print(
        json.dumps(
            [
                {
                    "pattern_key": proposal.pattern_key,
                    "example_count": proposal.example_count,
                    "average_delta": proposal.average_delta,
                    "proposal_text": proposal.proposal_text,
                    "status": proposal.status,
                }
                for proposal in proposals
            ],
            indent=2,
        )
    )
```

- [ ] **Step 5: Run calibration tests to verify they pass**

Run:

```bash
python3 -m pytest tests/test_calibration.py tests/test_cli_candidates.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/backstage_agent/calibration.py src/backstage_agent/cli.py tests/test_calibration.py
git commit -m "feat: propose scoring calibration changes"
```

---

### Task 11: Documentation And End-to-End Verification

**Files:**
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/module-guide.md`
- Optional Modify: `README.md` if command usage changes need public setup/operation notes.

**Interfaces:**
- Consumes: all new candidate scoring behavior from Tasks 1-10.
- Produces: updated project documentation and final verification evidence.

- [ ] **Step 1: Update project documentation**

Update `PROJECT_STATE.md` current capabilities to mention:

```markdown
- Candidate-first mutual-selection scoring that generates role and project-only candidates, extracts LLM features, matches local requirements, computes deterministic scores, and stores ranked bands.
- Human feedback capture for candidate score disagreement and calibration proposal generation.
```

Update `PROJECT_STATE.md` priorities to replace hard project-level filtering language with:

```markdown
- Preserve candidate-first scoring: project evaluation should influence candidate scores but should not silently hide roles before scoring.
```

Update `CHANGELOG.md` under Unreleased:

```markdown
### Added

- Added candidate-first mutual-selection scoring with LLM feature extraction, local requirement matching, deterministic score traces, ranked bands, draft suggestions, human feedback, and calibration proposals.

### Changed

- Changed scan orchestration so project evaluation contributes to candidate scoring instead of acting as a hard project-level filter for the new scoring path.
```

Update `ARCHITECTURE.md` and `docs/module-guide.md` to include the new modules:

```markdown
## Candidate Scoring

- `candidate_models.py` defines candidate, feature, requirement match, score, feedback, and calibration data structures.
- `candidate_generation.py` creates role and project-only candidates from parsed projects and roles.
- `feature_extractor.py` asks the LLM for structured features only.
- `requirement_matcher.py` checks extracted requirements against local actor facts.
- `scoring.py` computes deterministic scores, bands, caps, and ranks.
- `calibration.py` turns repeated human feedback patterns into scoring-rule proposals.
```

- [ ] **Step 2: Run focused test suite**

Run:

```bash
python3 -m pytest \
  tests/test_candidate_models.py \
  tests/test_candidate_generation.py \
  tests/test_requirement_matcher.py \
  tests/test_candidate_scoring.py \
  tests/test_feature_extractor.py \
  tests/test_candidate_storage.py \
  tests/test_agent_candidate_scoring.py \
  tests/test_cli_candidates.py \
  tests/test_ui_candidates.py \
  tests/test_calibration.py \
  tests/test_agent_review_gate.py \
  tests/test_storage_dashboard.py \
  tests/test_cli_summary.py \
  tests/test_ui_labels.py \
  -v
```

Expected: PASS.

- [ ] **Step 3: Run full test suite**

Run:

```bash
python3 -m pytest -v
```

Expected: PASS.

- [ ] **Step 4: Run CLI smoke check**

Run:

```bash
.venv/bin/python -m backstage_agent.cli candidates --limit 5
```

Expected: JSON array output. It may be empty on a fresh database, but the command must exit 0.

- [ ] **Step 5: Commit**

```bash
git add PROJECT_STATE.md CHANGELOG.md ARCHITECTURE.md docs/module-guide.md README.md
git commit -m "docs: document candidate scoring workflow"
```

