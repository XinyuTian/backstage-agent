from backstage_agent.candidate_generation import generate_candidates
from backstage_agent.candidate_models import CandidateType
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
    assert candidates[0].notice.role is None


def test_generate_project_only_candidate_when_roles_are_vague():
    vague = _role(role=None, role_key="")

    candidates = generate_candidates(project_id=11, project=_project(), stored_roles=[(21, vague)])

    assert len(candidates) == 1
    assert candidates[0].candidate_type is CandidateType.PROJECT_ONLY
