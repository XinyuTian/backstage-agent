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


def test_required_union_status_matches_actor_profile_scalar(actor_profile_factory):
    profile = actor_profile_factory(union_status="non-union")
    features = _features(
        {
            "union_status_required": {
                "required": True,
                "evidence": "Must be non-union.",
            }
        }
    )
    rules = {
        "known_requirements": {
            "union_status_required": {
                "profile_attribute": "union_status",
                "met_values": ["non-union"],
                "points_when_met": 3,
            }
        }
    }

    matches = match_requirements(features, profile, rules)

    assert matches[0].requirement_key == "union_status_required"
    assert matches[0].status is RequirementStatus.MET
    assert matches[0].local_value == "non-union"
    assert matches[0].score_impact == 3


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


def test_unknown_string_requirement_needs_user_input(actor_profile_factory):
    profile = actor_profile_factory()
    features = _features({"audition_song": "Prepare 32 bars."})

    matches = match_requirements(features, profile, _rules())

    assert matches[0].requirement_key == "audition_song"
    assert matches[0].required is True
    assert matches[0].evidence == "Prepare 32 bars."
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
