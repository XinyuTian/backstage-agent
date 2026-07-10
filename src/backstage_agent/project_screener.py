from __future__ import annotations

import json
from dataclasses import asdict, replace

from .identifiers import role_key as build_role_key
from .models import ActorProfile, CastingNotice, ProjectNotice, ScreeningDecision
from .screener import _avoidance_concerns, _llm_client
from .settings import Settings

PROJECT_GATE_ROLE = "__project_gate__"


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
            )
        return None

    def _llm_screen(self, notice: CastingNotice) -> ScreeningDecision:
        self._llm_calls += 1
        response = self._client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the first-pass project-level screener for casting projects. "
                        "Decide whether this project should proceed to role-level screening. "
                        "Focus only on project-wide fit: project type, location, shoot dates, "
                        "compensation, travel burden, and actor profile avoid terms. Reject "
                        "concrete project-wide conflicts. Do not reject for role-specific "
                        "gender, age, ethnicity, language, singing, wardrobe, or special-skill "
                        "requirements unless they apply to the entire project. This is an "
                        "optimistic first-pass selector; pass plausible projects so a stricter "
                        "project reviewer can make the gate decision. Return compact JSON with "
                        "score between 0 and 1, should_apply boolean, reasons array, and "
                        "concerns array."
                    ),
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
        data = json.loads(content)
        score = float(data.get("score", 0.0))
        return ScreeningDecision(
            notice=notice,
            score=score,
            should_apply=bool(data.get("should_apply", score >= self.settings.min_match_score)),
            reasons=list(data.get("reasons", [])),
            concerns=list(data.get("concerns", [])),
            llm_used=True,
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
