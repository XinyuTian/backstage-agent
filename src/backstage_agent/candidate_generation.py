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
