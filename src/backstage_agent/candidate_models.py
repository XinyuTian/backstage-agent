from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import CastingNotice


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
            role=None,
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
