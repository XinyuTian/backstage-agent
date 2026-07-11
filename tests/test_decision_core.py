import pytest

from backstage_agent.decision_core import (
    DecisionBucket,
    StructuredReview,
    StructuredScreening,
    resolve_final_bucket,
    load_screening_rules,
)


def _screening_data(**overrides):
    data = {
        "suggested_bucket": "auto_apply_draft",
        "role_type": "scripted_acting",
        "project_type": "theater",
        "career_value_score": 5,
        "required_preferences": [],
        "missing_preference_keys": [],
        "pay_burden": "low",
        "travel_burden": "low",
        "time_burden": "medium",
        "fit_reasons": ["Named scripted role"],
        "concerns": [],
        "evidence_snippets": ["Lead, Female, 30-50"],
        "confidence": 0.91,
    }
    data.update(overrides)
    return data


def test_decision_bucket_values_are_stable():
    assert DecisionBucket.AUTO_APPLY_DRAFT.value == "auto_apply_draft"
    assert DecisionBucket.READY_FOR_REVIEW.value == "ready_for_review"
    assert DecisionBucket.NEEDS_MY_PREFERENCE.value == "needs_my_preference"
    assert DecisionBucket.REJECT.value == "reject"
    assert DecisionBucket.DATA_PARSE_ERROR.value == "data_parse_error"


def test_structured_screening_validates_required_fields():
    parsed = StructuredScreening.from_json(_screening_data())

    assert parsed.suggested_bucket is DecisionBucket.AUTO_APPLY_DRAFT
    assert parsed.career_value_score == 5
    assert parsed.evidence_snippets == ["Lead, Female, 30-50"]


def test_structured_screening_rejects_missing_required_field():
    with pytest.raises(ValueError, match="missing required structured screening fields"):
        StructuredScreening.from_json({"suggested_bucket": "auto_apply_draft"})


def test_structured_screening_rejects_out_of_range_career_score():
    with pytest.raises(ValueError, match="career_value_score"):
        StructuredScreening.from_json(_screening_data(career_value_score=6))


def test_default_screening_rules_load():
    rules = load_screening_rules()

    assert rules.career_value["scripted_acting"] == 5
    assert rules.preferences["active_instagram_tagging"]["profile_key"] == (
        "comfortable_with_active_instagram_tagging"
    )


def test_resolver_sends_missing_preferences_to_needs_my_preference():
    screening = StructuredScreening.from_json(
        _screening_data(missing_preference_keys=["comfortable_with_haze"])
    )

    artifacts = resolve_final_bucket(screening=screening)

    assert artifacts.final_bucket is DecisionBucket.NEEDS_MY_PREFERENCE
    assert artifacts.reviewer_impact == "not_reviewed"


def test_reviewer_can_downgrade_auto_apply_one_step_with_evidence():
    screening = StructuredScreening.from_json(_screening_data())
    review = StructuredReview.from_json(
        {
            "verdict": "downgrade",
            "downgrade_to": "ready_for_review",
            "evidence_snippets": ["requires local rehearsal confirmation"],
            "reasons": ["Worth review before drafting"],
            "concerns": [],
            "confidence": 0.8,
        }
    )

    artifacts = resolve_final_bucket(screening=screening, review=review)

    assert artifacts.final_bucket is DecisionBucket.READY_FOR_REVIEW
    assert artifacts.reviewer_impact == "downgraded"


def test_reviewer_downgrade_without_evidence_is_ignored():
    screening = StructuredScreening.from_json(_screening_data())
    review = StructuredReview.from_json(
        {
            "verdict": "downgrade",
            "downgrade_to": "reject",
            "evidence_snippets": [],
            "reasons": ["Too risky"],
            "concerns": [],
            "confidence": 0.8,
        }
    )

    artifacts = resolve_final_bucket(screening=screening, review=review)

    assert artifacts.final_bucket is DecisionBucket.AUTO_APPLY_DRAFT
    assert artifacts.reviewer_impact == "ignored_no_evidence"
