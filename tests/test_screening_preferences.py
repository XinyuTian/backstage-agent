from backstage_agent import project_screener, reviewer, screener
from backstage_agent.decision_core import load_screening_rules


def test_active_instagram_tagging_is_a_known_allowed_preference():
    rules = load_screening_rules()
    prompt_text = "\n".join(
        [
            project_screener.PROJECT_SCREENING_ALLOWED_PREFERENCES,
            screener.ROLE_SCREENING_ALLOWED_PREFERENCES,
            reviewer.REVIEWER_ALLOWED_PREFERENCES,
        ]
    ).lower()

    assert rules.preferences["active_instagram_tagging"]["profile_key"] == (
        "comfortable_with_active_instagram_tagging"
    )
    assert "active instagram tagging" in prompt_text
    assert "comfortable_with_active_instagram_tagging" in prompt_text
    assert "do not reject" in prompt_text
