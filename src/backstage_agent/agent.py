from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime

from .candidate_models import CandidateFeatures, CandidateScore, RequirementMatch, ScoreBand
from .candidate_generation import generate_candidates
from .feature_extractor import FeatureExtractor
from .email_client import ImapEmailClient
from .parser import parse_project_notices
from .project_context import (
    with_project_page_context,
    with_project_role_context,
    with_project_shooting_info,
)
from .project_page_parser import parse_project_page_roles, project_page_context
from .requirement_matcher import match_requirements
from .scoring import load_scoring_rules, rank_candidates, score_candidate
from .settings import Settings, load_actor_profile
from .storage import DecisionStore
from .web_client import ProjectPageClient

CandidateScoreRecord = tuple[object, CandidateFeatures, list[RequirementMatch], CandidateScore]
_RANKING_INDEX_KEY = "_agent_candidate_index"


@dataclass(frozen=True)
class ScanResult:
    messages_seen: int
    projects_seen: int
    notices_seen: int
    candidates_scored: int = 0
    candidates_skipped_existing: int = 0
    draft_suggestions: int = 0


@dataclass(frozen=True)
class CandidateScoringResult:
    date: date
    overwrite: bool
    candidates_scored: int
    candidates_skipped_existing: int
    candidates_deleted: int


class BackstageAgent:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.profile = load_actor_profile(settings.actor_profile_path)
        self.email_client = ImapEmailClient(settings)
        self.store = DecisionStore(settings.database_path)
        self.project_pages = ProjectPageClient(settings)
        self.feature_extractor = FeatureExtractor(settings, self.profile)
        self.scoring_rules = load_scoring_rules()

    def scan(self, limit: int, days: int = 1, target_date: date | None = None) -> ScanResult:
        messages = self.email_client.fetch_messages(
            limit=limit,
            days=days,
            target_date=target_date,
        )
        projects_seen = 0
        notices_seen = 0
        seen_date = target_date or datetime.now().astimezone().date()

        for message in messages:
            projects = parse_project_notices(message)
            projects_seen += len(projects)
            for project in projects:
                project_id = self.store.upsert_project(project, seen_date=seen_date)
                html = self.project_pages.fetch_html(project.project_url)
                if html:
                    project = with_project_page_context(project, project_page_context(html))
                page_roles = parse_project_page_roles(project, html or "") if html else []
                if page_roles:
                    self.store.update_project_info(
                        project_id,
                        page_roles[0].shooting_locations,
                        page_roles[0].shooting_dates,
                    )
                    project = with_project_shooting_info(
                        project,
                        page_roles[0].shooting_locations,
                        page_roles[0].shooting_dates,
                    )
                    project = with_project_role_context(project, page_roles)

                for role in page_roles:
                    self.store.upsert_role(project_id, role)
                notices_seen += len(page_roles)

        scoring = self.score_candidates_for_date(seen_date, overwrite=False)
        candidate_rows = self.store.candidate_rows_for_date(seen_date.isoformat())
        return ScanResult(
            messages_seen=len(messages),
            projects_seen=projects_seen,
            notices_seen=notices_seen,
            candidates_scored=scoring.candidates_scored,
            candidates_skipped_existing=scoring.candidates_skipped_existing,
            draft_suggestions=sum(bool(row["draft_suggestion"]) for row in candidate_rows),
        )

    def score_candidates_for_date(
        self,
        target_date: date,
        overwrite: bool = False,
    ) -> CandidateScoringResult:
        target_date_text = target_date.isoformat()
        candidates_deleted = (
            self.store.clear_candidates_for_date(target_date_text) if overwrite else 0
        )
        existing_rows = [] if overwrite else self.store.candidate_rows_for_date(target_date_text)
        existing_identities = {_candidate_row_identity(row) for row in existing_rows}
        candidate_records: list[CandidateScoreRecord] = []
        candidates_skipped_existing = 0
        for project, stored_roles, project_id in self.store.candidate_rescore_sources_for_date(
            target_date_text
        ):
            for candidate in generate_candidates(project_id, project, stored_roles):
                if _candidate_identity(candidate) in existing_identities:
                    candidates_skipped_existing += 1
                    continue
                features, requirement_matches, score = self._score_candidate_with_fallback(candidate)
                candidate_records.append((candidate, features, requirement_matches, score))

        ranked_candidate_records = self._rank_with_existing(candidate_records, existing_rows)
        for candidate, features, requirement_matches, ranked_score in ranked_candidate_records:
            self.store.record_candidate(
                candidate,
                features,
                requirement_matches,
                ranked_score,
            )
        return CandidateScoringResult(
            date=target_date,
            overwrite=overwrite,
            candidates_scored=len(ranked_candidate_records),
            candidates_skipped_existing=candidates_skipped_existing,
            candidates_deleted=candidates_deleted,
        )

    def rescore_candidates_for_date(self, target_date: date) -> int:
        return self.score_candidates_for_date(target_date, overwrite=True).candidates_scored

    def _rank_with_existing(
        self,
        new_records: list[CandidateScoreRecord],
        existing_rows,
    ) -> list[CandidateScoreRecord]:
        existing_count = len(existing_rows)
        tagged_scores = [
            _tag_candidate_score(_candidate_score_from_row(row), index)
            for index, row in enumerate(existing_rows)
        ]
        tagged_scores.extend(
            _tag_candidate_score(score, existing_count + index)
            for index, (_, _, _, score) in enumerate(new_records)
        )
        if not tagged_scores:
            return []
        try:
            ranked_scores = rank_candidates(tagged_scores, self.scoring_rules)
        except Exception as exc:  # noqa: BLE001
            ranked_scores = _fallback_rank_candidates(tagged_scores, exc)
        ranked_by_index = {
            _candidate_score_index(score): _untag_candidate_score(score)
            for score in ranked_scores
        }
        for index, row in enumerate(existing_rows):
            ranked = ranked_by_index[index]
            self.store.update_candidate_rank(
                int(row["id"]),
                int(ranked.rank_score or ranked.overall_score),
                int(ranked.rank_position or 0),
            )
        return [
            (candidate, features, matches, ranked_by_index[existing_count + index])
            for index, (candidate, features, matches, _score) in enumerate(new_records)
        ]

    def _score_candidate_with_fallback(
        self,
        candidate,
    ) -> tuple[CandidateFeatures, list[RequirementMatch], CandidateScore]:
        try:
            features = self.feature_extractor.extract(candidate)
        except Exception as exc:  # noqa: BLE001
            return _fallback_candidate_artifacts(candidate, self.scoring_rules, "feature_extraction", exc)

        try:
            requirement_matches = match_requirements(
                features,
                self.profile,
                self.scoring_rules,
            )
        except Exception as exc:  # noqa: BLE001
            return _fallback_candidate_artifacts(
                candidate,
                self.scoring_rules,
                "requirement_matching",
                exc,
                features=features,
            )

        try:
            score = score_candidate(features, requirement_matches, self.scoring_rules)
        except Exception as exc:  # noqa: BLE001
            return _fallback_candidate_artifacts(
                candidate,
                self.scoring_rules,
                "scoring",
                exc,
                features=features,
                requirement_matches=requirement_matches,
            )

        return features, requirement_matches, score

def _fallback_candidate_artifacts(
    candidate,
    rules: dict,
    stage: str,
    exc: Exception,
    *,
    features: CandidateFeatures | None = None,
    requirement_matches: list[RequirementMatch] | None = None,
) -> tuple[CandidateFeatures, list[RequirementMatch], CandidateScore]:
    fallback = _fallback_metadata(candidate, stage, exc)
    resolved_features = _fallback_features(candidate, fallback, features)
    matches = requirement_matches or []
    return resolved_features, matches, CandidateScore(
        overall_score=0,
        score_band=ScoreBand.NOT_WORTH_APPLYING_TODAY,
        subscores={name: 0 for name in rules["component_weights"]},
        score_caps=["candidate_scoring_fallback"],
        positive_drivers=[],
        negative_drivers=[
            "Candidate scoring fallback used",
            f"{stage} failed: {fallback['error']}",
        ],
        score_trace={"fallback": fallback},
        draft_suggestion=False,
        scoring_version=str(rules["version"]),
    )


def _fallback_rank_candidates(scores: list[CandidateScore], exc: Exception) -> list[CandidateScore]:
    ranked = sorted(scores, key=lambda score: score.overall_score, reverse=True)
    fallback_scores: list[CandidateScore] = []
    for index, score in enumerate(ranked, start=1):
        fallback = {
            "used": True,
            "stage": "ranking",
            "error": f"{exc.__class__.__name__}: {exc}",
            "draft_allowed": False,
        }
        fallback_scores.append(
            replace(
                score,
                rank_score=score.overall_score,
                rank_position=index,
                negative_drivers=[
                    *score.negative_drivers,
                    "Candidate scoring fallback used",
                    f"ranking failed: {fallback['error']}",
                ],
                score_trace={
                    **score.score_trace,
                    "fallback": fallback,
                },
                draft_suggestion=False,
            )
        )
    return fallback_scores


def _tag_candidate_score(score: CandidateScore, index: int) -> CandidateScore:
    return replace(
        score,
        score_trace={
            **score.score_trace,
            _RANKING_INDEX_KEY: index,
        },
    )


def _candidate_score_index(score: CandidateScore) -> int:
    return int(score.score_trace[_RANKING_INDEX_KEY])


def _untag_candidate_score(score: CandidateScore) -> CandidateScore:
    score_trace = dict(score.score_trace)
    score_trace.pop(_RANKING_INDEX_KEY, None)
    return replace(score, score_trace=score_trace)


def _candidate_identity(candidate) -> tuple[str, str]:
    return candidate.candidate_type.value, candidate.role_key or candidate.project_key


def _candidate_row_identity(row) -> tuple[str, str]:
    return str(row["candidate_type"]), str(row["role_key"] or row["project_key"])


def _candidate_score_from_row(row) -> CandidateScore:
    payload = json.loads(row["score_json"])
    return CandidateScore(
        overall_score=int(row["overall_score"]),
        score_band=ScoreBand(str(row["score_band"])),
        subscores={key: int(value) for key, value in payload.get("subscores", {}).items()},
        score_caps=list(payload.get("score_caps", [])),
        positive_drivers=list(payload.get("positive_drivers", [])),
        negative_drivers=list(payload.get("negative_drivers", [])),
        score_trace=dict(payload.get("score_trace", {})),
        draft_suggestion=bool(row["draft_suggestion"]),
        scoring_version=str(row["scoring_version"]),
        rank_score=row["rank_score"],
        rank_position=row["rank_position"],
    )


def _fallback_features(candidate, fallback: dict, existing: CandidateFeatures | None) -> CandidateFeatures:
    if existing is not None:
        return replace(
            existing,
            raw={
                **existing.raw,
                "fallback": fallback,
            },
        )

    text = candidate.notice.description or candidate.notice.raw_text or candidate.title
    return CandidateFeatures(
        role_type="unknown",
        project_type="unknown",
        requirements={},
        project_signals={"candidate_scoring_fallback": True},
        compensation={"type": "unknown", "amount_known": False},
        uncertainty={"compensation_missing": True, "role_details_sparse": True},
        evidence_snippets=[text] if text else [],
        raw={"fallback": fallback},
    )


def _fallback_metadata(candidate, stage: str, exc: Exception) -> dict:
    return {
        "used": True,
        "stage": stage,
        "error": f"{exc.__class__.__name__}: {exc}",
        "candidate_type": candidate.candidate_type.value,
        "project_key": candidate.project_key,
        "role_key": candidate.role_key,
        "draft_allowed": False,
    }
