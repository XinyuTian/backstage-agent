from backstage_agent.decision_core import DecisionBucket
from backstage_agent.screener import RoleScreener


def test_role_llm_returns_structured_auto_apply_bucket(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
    structured_screening_payload_factory,
):
    screener = RoleScreener(settings_factory(), actor_profile_factory())
    screener._client = fake_chat_client_factory([structured_screening_payload_factory()])

    decision = screener._llm_screen(casting_notice_factory())

    assert decision.should_apply is True
    assert decision.final_bucket == DecisionBucket.AUTO_APPLY_DRAFT.value
    assert decision.classifier_json["role_type"] == "scripted_acting"
    assert decision.schema_error == ""


def test_role_llm_repairs_invalid_structured_response_once(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
    structured_screening_payload_factory,
):
    screener = RoleScreener(settings_factory(), actor_profile_factory())
    screener._client = fake_chat_client_factory(
        [
            {"score": 0.9, "should_apply": True},
            structured_screening_payload_factory(suggested_bucket="ready_for_review"),
        ]
    )

    decision = screener._llm_screen(casting_notice_factory())

    assert decision.final_bucket == DecisionBucket.READY_FOR_REVIEW.value
    assert decision.should_apply is False
    assert len(screener._client.calls) == 2
    assert "repair" in screener._client.calls[1]["messages"][0]["content"].lower()


def test_role_llm_invalid_retry_becomes_data_parse_error(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
):
    screener = RoleScreener(settings_factory(), actor_profile_factory())
    screener._client = fake_chat_client_factory([{"score": 0.9}, {"still": "bad"}])

    decision = screener._llm_screen(casting_notice_factory())

    assert decision.should_apply is False
    assert decision.final_bucket == DecisionBucket.DATA_PARSE_ERROR.value
    assert "structured screening" in decision.schema_error
