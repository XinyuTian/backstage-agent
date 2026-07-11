from __future__ import annotations

import json
from dataclasses import asdict, replace

from .decision_core import (
    DecisionBucket,
    StructuredScreening,
    resolve_final_bucket,
    should_draft_bucket,
)
from .identifiers import role_key as build_role_key
from .models import ActorProfile, CastingNotice, ProjectNotice, ScreeningDecision
from .screener import _avoidance_concerns, _llm_client
from .settings import Settings

PROJECT_GATE_ROLE = "__project_gate__"
PROJECT_SCREENING_ALLOWED_PREFERENCES = (
    "Do not reject projects or roles because they require active Instagram tagging "
    "when the actor profile has comfortable_with_active_instagram_tagging=true."
)


class ProjectScreener:
    def __init__(self, settings: Settings, profile: ActorProfile):
        self.settings = settings
        self.profile = profile
        self._llm_calls = 0
        self._client = _llm_client(settings)

    def screen(self, project: ProjectNotice) -> ScreeningDecision:
        notice = project_to_notice(project)
        local_decision = self._local_screen(notice)
        if local_decision is not None:
            return local_decision
        if self._client is None or self._llm_calls >= self.settings.max_llm_calls_per_scan:
            return ScreeningDecision(
                notice=notice,
                score=0.0,
                should_apply=False,
                reasons=[
                    "Rejected because project LLM screening was unavailable: "
                    "no API key or call budget."
                ],
                final_bucket=DecisionBucket.READY_FOR_REVIEW.value,
            )
        return self._llm_screen(notice)

    def _local_screen(self, notice: CastingNotice) -> ScreeningDecision | None:
        concerns = _avoidance_concerns(notice, self.profile.avoid)
        if concerns:
            return ScreeningDecision(
                notice=notice,
                score=0.0,
                should_apply=False,
                reasons=["Rejected by project-level actor profile avoidance rules."],
                concerns=concerns,
                final_bucket=DecisionBucket.REJECT.value,
            )
        if _is_senior_community_project(notice):
            return ScreeningDecision(
                notice=notice,
                score=0.0,
                should_apply=False,
                reasons=[
                    "Rejected locally: project is centered on an older/senior arts community, "
                    "which does not match the actor's current career-starting goals."
                ],
                final_bucket=DecisionBucket.REJECT.value,
            )
        return None

    def _llm_screen(self, notice: CastingNotice) -> ScreeningDecision:
        self._llm_calls += 1
        data, error = self._request_structured_screening(notice)
        if data is None:
            artifacts = resolve_final_bucket(schema_error=error)
            return ScreeningDecision(
                notice=notice,
                score=0.0,
                should_apply=False,
                reasons=["Data/parse error from first-pass project LLM screening."],
                concerns=[error] if error else [],
                llm_used=True,
                final_bucket=artifacts.final_bucket.value,
                schema_error=artifacts.schema_error,
            )
        screening = StructuredScreening.from_json(data)
        artifacts = resolve_final_bucket(screening=screening)
        return ScreeningDecision(
            notice=notice,
            score=screening.confidence,
            should_apply=should_draft_bucket(artifacts.final_bucket),
            reasons=screening.fit_reasons,
            concerns=screening.concerns,
            llm_used=True,
            final_bucket=artifacts.final_bucket.value,
            classifier_json=artifacts.classifier_json,
            reviewer_impact=artifacts.reviewer_impact,
        )

    def _request_structured_screening(self, notice: CastingNotice) -> tuple[dict | None, str]:
        last_error = ""
        for attempt in range(2):
            prompt = _PROJECT_STRUCTURED_SCREENING_PROMPT
            if attempt:
                prompt = (
                    "Repair the previous response. Return only valid JSON matching the "
                    "structured screening schema. "
                    f"Previous error: {last_error}"
                )
            response = self._client.chat.completions.create(
                model=self.settings.llm_model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": prompt,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "actor_profile": asdict(self.profile),
                                "project_notice": asdict(notice),
                                "minimum_score": self.settings.min_match_score,
                            },
                            default=str,
                        ),
                    },
                ],
            )
            content = response.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
                StructuredScreening.from_json(data)
                return data, ""
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = f"structured screening validation failed: {exc}"
        return None, last_error


_PROJECT_STRUCTURED_SCREENING_PROMPT = (
    "You are the first-pass project-level screener for casting projects. "
    "Decide whether this project should proceed to role-level screening. "
    "Return only JSON with fields: suggested_bucket, role_type, project_type, "
    "career_value_score, required_preferences, missing_preference_keys, "
    "pay_burden, travel_burden, time_burden, fit_reasons, concerns, "
    "evidence_snippets, confidence. suggested_bucket must be one of "
    "auto_apply_draft, ready_for_review, needs_my_preference, reject, "
    "data_parse_error. Focus only on project-wide fit: project type, location, "
    "shoot dates, compensation, travel burden, and actor profile avoid terms. "
    "Reject concrete project-wide conflicts. Do not reject for role-specific "
    "gender, age, ethnicity, language, singing, wardrobe, or special-skill "
    "requirements unless they apply to the entire project. "
    f"{PROJECT_SCREENING_ALLOWED_PREFERENCES} "
    "Use auto_apply_draft when the project should proceed to role screening now, "
    "ready_for_review when the project is promising but should be eyeballed, "
    "needs_my_preference for unknown reusable actor preferences, reject for "
    "concrete conflicts, and data_parse_error only when too malformed to classify."
)


def project_to_notice(project: ProjectNotice) -> CastingNotice:
    description = "\n".join(
        part
        for part in (
            project.description,
            f"Shooting locations: {project.shooting_locations}" if project.shooting_locations else None,
            f"Shooting dates: {project.shooting_dates}" if project.shooting_dates else None,
            f"Project labels: {', '.join(project.project_labels)}" if project.project_labels else None,
        )
        if part
    )
    key = build_role_key(
        project.project_key,
        project.project_url,
        PROJECT_GATE_ROLE,
        f"{project.title} - Project Gate",
        description,
    )
    return CastingNotice(
        source_message_id=project.source_message_id,
        title=f"{project.title} - Project Gate",
        project=project.title,
        role=PROJECT_GATE_ROLE,
        location=project.shooting_locations,
        compensation=None,
        description=description,
        application_url=project.project_url,
        raw_text="\n".join(part for part in (project.raw_text, description) if part),
        project_date=project.project_date,
        project_labels=project.project_labels,
        project_key=project.project_key,
        role_key=key,
        shooting_locations=project.shooting_locations,
        shooting_dates=project.shooting_dates,
    )


def with_project_role_context(project: ProjectNotice, roles: list[CastingNotice]) -> ProjectNotice:
    context_parts = []
    compensations = [
        compensation.strip()
        for role in roles
        if (compensation := getattr(role, "compensation", None)) and compensation.strip()
    ]
    if compensations:
        context_parts.append(f"Role compensation: {'; '.join(dict.fromkeys(compensations))}")
    role_summaries = [
        f"{role_name}: {description}"
        for role in roles[:4]
        if (role_name := getattr(role, "role", None))
        and (description := getattr(role, "description", None))
    ]
    if role_summaries:
        context_parts.append("Role summaries: " + " | ".join(role_summaries))
    if not context_parts:
        return project
    added_context = "\n".join(context_parts)
    return replace(
        project,
        description="\n".join([project.description, added_context]).strip(),
        raw_text="\n".join([project.raw_text, added_context]).strip(),
    )


def with_project_page_context(project: ProjectNotice, page_context: str) -> ProjectNotice:
    page_context = page_context.strip()
    if not page_context or page_context in project.raw_text:
        return project
    return replace(
        project,
        description="\n".join([project.description, page_context]).strip(),
        raw_text="\n".join([project.raw_text, page_context]).strip(),
    )


def _is_senior_community_project(notice: CastingNotice) -> bool:
    text = "\n".join([notice.title, notice.project or "", notice.description, notice.raw_text]).lower()
    senior_terms = (
        "55 and above community",
        "55+ community",
        "older people in the arts",
        "senior theatre guild",
        "senior theater guild",
        "senior arts community",
    )
    if any(term in text for term in senior_terms):
        return True
    return "virtual staged reading event" in text and "jack truman productions" in text


def with_project_shooting_info(
    project: ProjectNotice,
    shooting_locations: str | None,
    shooting_dates: str | None,
) -> ProjectNotice:
    if not shooting_locations and not shooting_dates:
        return project
    return replace(
        project,
        shooting_locations=shooting_locations or project.shooting_locations,
        shooting_dates=shooting_dates or project.shooting_dates,
    )
