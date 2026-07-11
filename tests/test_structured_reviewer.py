from backstage_agent.decision_core import DecisionBucket
from backstage_agent.reviewer import DecisionReviewer


def test_reviewer_confirm_keeps_auto_apply_bucket(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
    structured_review_payload_factory,
):
    reviewer = DecisionReviewer(_reviewer_settings(settings_factory), actor_profile_factory())
    reviewer._client = fake_chat_client_factory(
        [structured_review_payload_factory(verdict="confirm", downgrade_to=None)]
    )

    review = reviewer.review(
        casting_notice_factory(),
        initial_bucket=DecisionBucket.AUTO_APPLY_DRAFT.value,
    )

    assert review.status == "approved"
    assert review.final_bucket == DecisionBucket.AUTO_APPLY_DRAFT.value
    assert review.reviewer_impact == "confirmed"


def test_reviewer_downgrades_auto_apply_to_ready_for_review_with_evidence(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
    structured_review_payload_factory,
):
    reviewer = DecisionReviewer(_reviewer_settings(settings_factory), actor_profile_factory())
    reviewer._client = fake_chat_client_factory(
        [
            structured_review_payload_factory(
                verdict="downgrade",
                downgrade_to="ready_for_review",
                evidence_snippets=["requires late-night shoot confirmation"],
            )
        ]
    )

    review = reviewer.review(
        casting_notice_factory(),
        initial_bucket=DecisionBucket.AUTO_APPLY_DRAFT.value,
    )

    assert review.status == "hold"
    assert review.final_bucket == DecisionBucket.READY_FOR_REVIEW.value
    assert review.reviewer_impact == "downgraded"


def test_reviewer_repairs_invalid_structured_response_once(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    fake_chat_client_factory,
    structured_review_payload_factory,
):
    reviewer = DecisionReviewer(_reviewer_settings(settings_factory), actor_profile_factory())
    reviewer._client = fake_chat_client_factory(
        [
            {"status": "approved"},
            structured_review_payload_factory(verdict="confirm", downgrade_to=None),
        ]
    )

    review = reviewer.review(
        casting_notice_factory(),
        initial_bucket=DecisionBucket.AUTO_APPLY_DRAFT.value,
    )

    assert review.status == "approved"
    assert len(reviewer._client.calls) == 2
    assert "repair" in reviewer._client.calls[1]["messages"][0]["content"].lower()


def _reviewer_settings(settings_factory):
    return settings_factory(
        ai_builder_api_key="unused",
        max_reviewer_calls_per_scan=2,
    )
