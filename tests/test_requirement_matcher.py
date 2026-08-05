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


def test_empty_requirements_are_ignored(actor_profile_factory):
    features = _features(
        {
            "null_value": None,
            "empty_text": "   ",
            "empty_list": [],
            "empty_object": {},
            "empty_wrapper": {"required": True, "evidence": None},
            "real_requirement": {
                "required": True,
                "evidence": "Must juggle fire.",
            },
        }
    )

    matches = match_requirements(features, actor_profile_factory(), _rules())

    assert [match.requirement_key for match in matches] == ["real_requirement"]


def test_not_specified_placeholder_wrappers_are_ignored(actor_profile_factory):
    features = _features(
        {
            "requirement_1": {
                "type": "age_range",
                "value": "20-30",
                "evidence": "Day Player, 20-30",
            },
            "requirement_2": {
                "type": "gender",
                "value": "not specified",
                "evidence": None,
            },
            "requirement_3": {
                "type": "ethnicity",
                "value": "NoT SpEcIfIeD",
                "evidence": "",
            },
            "requirement_4": {
                "type": "location",
                "value": "Antioch, CA",
                "evidence": "Shooting locations: Antioch, CA",
            },
            "requirement_5": {
                "type": "special_instruction",
                "value": "not specified",
                "evidence": "Applicant must confirm this requirement directly.",
            },
        }
    )

    matches = match_requirements(features, actor_profile_factory(), _rules())

    assert [match.requirement_key for match in matches] == [
        "requirement_1",
        "requirement_4",
        "requirement_5",
    ]


def test_not_specified_wrappers_with_other_substantive_fields_are_retained(
    actor_profile_factory,
):
    features = _features(
        {
            "union_constraint": {
                "type": "union_status",
                "value": "not specified",
                "evidence": None,
                "constraint": "Must be SAG-AFTRA",
            },
            "capped_requirement": {
                "type": "special_instruction",
                "value": "NOT SPECIFIED",
                "evidence": "",
                "score_cap": 50,
            },
        }
    )

    matches = match_requirements(features, actor_profile_factory(), _rules())

    assert [match.requirement_key for match in matches] == [
        "union_constraint",
        "capped_requirement",
    ]


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


def test_numbered_gender_requirement_mismatches_female_profile(actor_profile_factory):
    features = _features(
        {
            "requirement_1": {
                "requirement": "Gender: Male",
                "evidence": "Kenny - Supporting, Male, 20-40",
            }
        }
    )
    matches = match_requirements(
        features, actor_profile_factory(genders=["female"]), _rules()
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.NOT_MET
    assert matches[0].required is True
    assert matches[0].local_value == "female"


def test_inferred_requirement_is_visible_but_not_applicable(actor_profile_factory):
    matches = match_requirements(
        _features(
            {
                "gender": {
                    "value": "Male",
                    "required": True,
                    "evidence": "Masculine presentation preferred.",
                    "certainty": "inferred",
                }
            }
        ),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )

    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.NOT_APPLICABLE
    assert matches[0].required is False
    assert matches[0].score_impact == 0


def test_explicit_canonical_gender_from_combined_evidence_mismatches(
    actor_profile_factory,
):
    matches = match_requirements(
        _features(
            {
                "gender": {
                    "value": "Male",
                    "required": True,
                    "evidence": "Lead, Male, 18-28",
                    "certainty": "explicit",
                },
                "age_range": {
                    "value": "18-28",
                    "required": True,
                    "evidence": "Lead, Male, 18-28",
                    "certainty": "explicit",
                },
            }
        ),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )

    gender = next(match for match in matches if match.requirement_key == "gender")
    assert gender.status is RequirementStatus.NOT_MET
    assert gender.required is True


def test_canonical_gender_requirement_mismatches_female_profile(actor_profile_factory):
    matches = match_requirements(
        _features({"gender": "Male"}),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.NOT_MET
    assert matches[0].required is True


def test_gender_prefixed_key_mismatches_female_profile(actor_profile_factory):
    matches = match_requirements(
        _features(
            {
                "gender_male": {
                    "required": True,
                    "evidence": "Looking for: Male, 25-35",
                }
            }
        ),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.NOT_MET
    assert matches[0].required is True


def test_female_gender_requirement_matches_female_profile(actor_profile_factory):
    matches = match_requirements(
        _features({"gender": "Female"}),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    assert matches[0].status is RequirementStatus.MET


def test_any_gender_requirement_matches_female_profile(actor_profile_factory):
    features = _features(
        {
            "requirement_1": {
                "type": "gender",
                "value": "Any gender",
                "evidence": "Open to any gender.",
            }
        }
    )
    matches = match_requirements(
        features, actor_profile_factory(genders=["female"]), _rules()
    )
    assert matches[0].requirement_key == "gender"
    assert matches[0].status is RequirementStatus.MET


def test_open_gender_requirement_matches_female_profile(actor_profile_factory):
    matches = match_requirements(
        _features({"gender": "Open"}),
        actor_profile_factory(genders=["female"]),
        _rules(),
    )
    assert matches[0].status is RequirementStatus.MET


def test_unrelated_numbered_requirement_remains_unknown(actor_profile_factory):
    features = _features(
        {
            "requirement_1": {
                "requirement": "Natural screen presence",
                "evidence": "Natural, authentic screen presence.",
            }
        }
    )
    matches = match_requirements(features, actor_profile_factory(), _rules())
    assert matches[0].requirement_key == "requirement_1"
    assert matches[0].status is RequirementStatus.UNKNOWN_NEEDS_USER_INPUT
