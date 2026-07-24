from __future__ import annotations

from dataclasses import replace

from .models import CastingNotice, ProjectNotice


def with_project_role_context(
    project: ProjectNotice,
    roles: list[CastingNotice],
) -> ProjectNotice:
    context_parts = []
    compensations = [
        compensation.strip()
        for role in roles
        if (compensation := role.compensation) and compensation.strip()
    ]
    if compensations:
        context_parts.append(f"Role compensation: {'; '.join(dict.fromkeys(compensations))}")
    role_summaries = [
        f"{role.role}: {role.description}"
        for role in roles[:4]
        if role.role and role.description
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
