import pytest

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


def test_feature_extractor_normalizes_list_requirements(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
    payload = {
        "role_type": "commercial",
        "project_type": "commercial",
        "requirements": [
            {
                "key": "gender_male",
                "required": True,
                "evidence": "Looking for: Male, 25-35",
            },
            "Available July 23",
        ],
        "project_signals": {},
        "compensation": {},
        "uncertainty": {},
        "evidence_snippets": ["Looking for: Male, 25-35"],
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

    assert features.requirements["gender_male"]["required"] is True
    assert features.requirements["available_july_23"]["evidence"] == "Available July 23"


def test_feature_extractor_normalizes_loose_fact_containers(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
    payload = {
        "role_type": "commercial",
        "project_type": "commercial",
        "requirements": {},
        "project_signals": ["public performance", "career goal alignment high"],
        "compensation": "Paid $350",
        "uncertainty": ["schedule conflict unknown"],
        "evidence_snippets": "Paid $350",
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

    assert features.project_signals["public_performance"] is True
    assert features.project_signals["career_goal_alignment"] == "high"
    assert features.compensation["raw"] == "Paid $350"
    assert features.uncertainty["schedule_conflict_unknown"] is True
    assert features.evidence_snippets == ["Paid $350"]


def test_feature_extractor_rejects_non_object_payload(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
    extractor = FeatureExtractor(settings_factory(), actor_profile_factory())
    extractor._client = fake_chat_client_factory(['["not", "an", "object"]'])
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )

    with pytest.raises(ValueError, match="feature extraction payload must be a JSON object"):
        extractor.extract(candidate)


def test_feature_extractor_retries_malformed_json_once(
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
    }
    extractor = FeatureExtractor(settings_factory(), actor_profile_factory())
    extractor._client = fake_chat_client_factory(['{"role_type": "broken"', payload])
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
    assert len(extractor._client.calls) == 2


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {
                "role_type": "",
                "project_type": "theater",
                "requirements": {},
                "project_signals": {},
                "compensation": {},
                "uncertainty": {},
                "evidence_snippets": [],
            },
            "feature extraction field role_type must be a non-empty string",
        ),
        (
            {
                "role_type": "scripted_acting",
                "project_type": None,
                "requirements": {},
                "project_signals": {},
                "compensation": {},
                "uncertainty": {},
                "evidence_snippets": [],
            },
            "feature extraction field project_type must be a non-empty string",
        ),
        (
            {
                "role_type": "scripted_acting",
                "project_type": "theater",
                "requirements": None,
                "project_signals": {},
                "compensation": {},
                "uncertainty": {},
                "evidence_snippets": [],
            },
            "feature extraction field requirements must be a dict",
        ),
    ],
)
def test_feature_extractor_validates_schema(
    payload,
    message,
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
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

    with pytest.raises(ValueError, match=message):
        extractor.extract(candidate)


def test_feature_extractor_requires_llm_client(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
):
    extractor = FeatureExtractor(
        settings_factory(openai_api_key=None),
        actor_profile_factory(),
    )
    extractor._client = None
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )

    with pytest.raises(
        ValueError,
        match="feature extraction unavailable: no LLM client configured",
    ):
        extractor.extract(candidate)


def test_feature_extractor_respects_scan_llm_budget(
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
    }
    extractor = FeatureExtractor(settings_factory(max_llm_calls_per_scan=1), actor_profile_factory())
    extractor._client = fake_chat_client_factory([payload, payload])
    candidate = CandidateInput.role_candidate(
        project_id=1,
        role_id=2,
        project_key="project",
        role_key="role",
        title="Play - Lead",
        notice=casting_notice_factory(),
    )

    extractor.extract(candidate)

    with pytest.raises(
        ValueError,
        match="feature extraction unavailable: LLM call budget exhausted",
    ):
        extractor.extract(candidate)


def test_feature_extractor_supports_project_only_candidates(
    settings_factory,
    actor_profile_factory,
    fake_chat_client_factory,
):
    payload = {
        "role_type": "project_only",
        "project_type": "community_theater",
        "requirements": {},
        "project_signals": {"career_goal_alignment": "medium"},
        "compensation": {"type": "unknown"},
        "uncertainty": {"role_details_sparse": True},
        "evidence_snippets": ["Seeking ensemble members for a staged reading."],
    }
    extractor = FeatureExtractor(settings_factory(), actor_profile_factory())
    extractor._client = fake_chat_client_factory([payload])
    candidate = CandidateInput.project_only_candidate(
        project_id=7,
        project_key="project-key",
        title="Neighborhood Players Staged Reading",
        source_message_id="m7",
        description="Seeking ensemble members for a staged reading.",
        application_url=None,
    )

    features = extractor.extract(candidate)

    assert features.role_type == "project_only"
    assert features.project_type == "community_theater"
    assert features.evidence_snippets == ["Seeking ensemble members for a staged reading."]
