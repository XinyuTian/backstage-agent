import pytest

from backstage_agent.screener import RoleScreener


def test_local_screener_rejects_avoid_terms(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
):
    profile = actor_profile_factory(
        age_range="25-35",
        skills=["improv"],
        avoid=["explicit nudity"],
        preferred_roles=["commercial"],
    )
    notice = casting_notice_factory(
        title="Role",
        project=None,
        role=None,
        location=None,
        compensation=None,
        description="Contains explicit nudity",
        raw_text="Contains explicit nudity",
    )

    decision = RoleScreener(settings_factory(openai_api_key=None), profile).screen(notice)

    assert decision.should_apply is False
    assert decision.score == 0
    assert decision.concerns == ["explicit nudity"]


def test_local_screener_does_not_reject_unpaid_roles_when_profile_allows_them(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
):
    profile = actor_profile_factory(
        age_range="25-35",
        skills=["improv"],
        avoid=["unreimbursed travel expenses"],
        preferred_roles=["film"],
        attributes={"comfortable_with_unpaid_roles": "true"},
    )
    notice = casting_notice_factory(
        title="That Night at Trixies - Sierra",
        project="That Night at Trixies",
        role="Sierra",
        location=None,
        compensation="Unpaid",
        description="Supporting, 20-25. Improv-friendly short film role.",
        raw_text="Short Film\nSierra\nSupporting, Female, 20-25\nImprov-friendly role.\nUnpaid",
    )

    decision = RoleScreener(settings_factory(openai_api_key=None), profile)._local_screen(notice)

    assert decision is None


@pytest.mark.parametrize(
    ("title", "project", "role", "description", "raw_text"),
    [
        (
            "Lunar 5 - Dan",
            "Lunar 5",
            "Dan",
            "Lead. Male, 18-50",
            "Dan\nLead. Male, 18-50",
        ),
        (
            "Run for Your Wife - John Smith",
            "Run for Your Wife",
            "John Smith",
            "Lead, Male, 30-50\nCharming London taxi driver married to two different women.",
            "Run for Your Wife\nJohn Smith\nLead, Male, 30-50\nCharming London taxi driver married to two different women.",
        ),
        (
            "Behind The Confessional - Male Lead",
            "Behind The Confessional",
            "Male Lead",
            "Lead, 18-35. A calm and emotionally layered man.",
            "Male Lead\nLead, 18-35\nA calm and emotionally layered man.",
        ),
        (
            "Lunar 5 - Shamgar",
            "Lunar 5",
            "Shamgar",
            "Supporting, 18-50. A noble warrior carrying the emotional burden of his past.",
            "Shamgar\nSupporting, 18-50\nA noble warrior carrying the emotional burden of his past.",
        ),
        (
            "Virtual Staged Reading Event - Actor 1",
            "Virtual Staged Reading Event",
            "Actor 1",
            "Lead, 18-85. To read the roles of Lee, Stan and Pastor.",
            "Actor 1\nLead, 18-85\nTo read the roles of Lee, Stan and Pastor.",
        ),
        (
            "Lunar 5 - Tristan 216",
            "Lunar 5",
            "Tristan 216",
            "Lead, 20-59. His movements are mechanical. He is the villain.",
            "Tristan 216\nLead, 20-59\nHis movements are mechanical. He is the villain.",
        ),
    ],
    ids=[
        "explicit-male-line",
        "explicit-male-beats-wife-title",
        "male-role-name",
        "male-pronoun",
        "male-staged-reading-names",
        "male-villain-pronoun",
    ],
)
def test_local_screener_rejects_male_role_signals_before_llm(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    title,
    project,
    role,
    description,
    raw_text,
):
    decision = RoleScreener(
        settings_factory(max_llm_calls_per_scan=1),
        actor_profile_factory(),
    ).screen(
        casting_notice_factory(
            title=title,
            project=project,
            role=role,
            location="Remote",
            compensation=None,
            description=description,
            raw_text=raw_text,
        )
    )

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "gender requirement" in decision.reasons[0]


def test_local_screener_rejects_required_real_singing_before_llm(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
):
    profile = actor_profile_factory(skills=["dance"], attributes={"can_sing": "false"})
    notice = casting_notice_factory(
        title="Relive The Music - Female Singer",
        project="Relive The Music",
        role="Female Singer",
        location=None,
        compensation=None,
        description="Lead, 18+. Must be a strong vocalist with ability to harmonize.",
        raw_text="Female Singer\nLead, 18+\nMust be a strong vocalist with ability to harmonize.",
    )

    decision = RoleScreener(settings_factory(), profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "requires real singing" in decision.reasons[0]


@pytest.mark.parametrize(
    ("title", "project", "role", "description", "raw_text"),
    [
        (
            "Nectar Lawyer Brunch For Two - Brunch Guests",
            "Nectar Lawyer Brunch For Two",
            "Brunch Guests",
            "Background / Extra, 20-50. Non-speaking brunch guests.",
            "Female Singer\nLead, Female, 18+\nApply\nNectar Lawyer Brunch For Two\nBrunch Guests\nBackground / Extra, 20-50. Non-speaking brunch guests.",
        ),
        (
            "Short Film - Jazz Singer",
            "Short Film",
            "Jazz Singer",
            "Supporting, 30-45. A retired performer in a dramatic scene. No musical performance listed.",
            "Jazz Singer\nSupporting, 30-45\nA retired performer in a dramatic scene.",
        ),
    ],
    ids=["other-role-singer-noise", "singer-character-no-required-singing"],
)
def test_local_screener_does_not_treat_singing_noise_as_requirement(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    title,
    project,
    role,
    description,
    raw_text,
):
    profile = actor_profile_factory(attributes={"can_sing": "false"})
    decision = RoleScreener(settings_factory(openai_api_key=None), profile).screen(
        casting_notice_factory(
            title=title,
            project=project,
            role=role,
            location=None,
            compensation=None,
            description=description,
            raw_text=raw_text,
        )
    )

    assert _llm_unavailable(decision)


def test_local_screener_keeps_overlapping_age_for_llm(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
):
    decision = RoleScreener(
        settings_factory(openai_api_key=None),
        actor_profile_factory(),
    ).screen(
        casting_notice_factory(
            title="Behind the Confessional - Zella Marchand",
            project="Behind the Confessional",
            role="Zella Marchand",
            location="Worldwide",
            compensation=None,
            description="Lead. Female, 18-35",
            raw_text="Zella Marchand\nLead. Female, 18-35",
        )
    )

    assert _llm_unavailable(decision)


@pytest.mark.parametrize(
    ("title", "project", "role", "description", "raw_text", "expected_reason"),
    [
        (
            "Tejidos - Adriana Nava",
            "Tejidos",
            "Adriana Nava",
            "Supporting. Female, 35-50",
            "Tejidos\nAdriana Nava\nSupporting. Female, 35-50",
            "identity or language signals",
        ),
        (
            "The Last Bugle - Allied Nurses",
            "The Last Bugle",
            "Allied Nurses",
            "Lead, 18-45. Appearance: Look like Angels of Mercy.",
            "Allied Nurses\nLead, 18-45\nAppearance: Look like Angels of Mercy.",
            "White/Caucasian",
        ),
    ],
    ids=["latina-name-signal", "white-appearance-signal"],
)
def test_local_screener_rejects_nonmatching_identity_signals(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    title,
    project,
    role,
    description,
    raw_text,
    expected_reason,
):
    profile = actor_profile_factory(
        ethnicities=["Asian"],
        skills=["Mandarin Chinese", "English"],
    )
    decision = RoleScreener(settings_factory(), profile).screen(
        casting_notice_factory(
            title=title,
            project=project,
            role=role,
            location="San Francisco",
            compensation=None,
            description=description,
            raw_text=raw_text,
        )
    )

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert expected_reason in decision.reasons[0]


@pytest.mark.parametrize(
    ("title", "project", "role", "description", "raw_text"),
    [
        (
            "Family Drama - Mei",
            "Family Drama",
            "Mei",
            "Lead. Female, 18-35. Mandarin speaker.",
            "Mei\nLead. Female, 18-35. Mandarin speaker.",
        ),
        (
            "Tejidos - Nurse",
            "Tejidos",
            "Nurse",
            "Supporting. Female, 30-45",
            "Tejidos\nNurse\nSupporting. Female, 30-45",
        ),
    ],
    ids=["matching-language-signal", "project-title-only-signal"],
)
def test_local_screener_allows_matching_or_project_only_identity_signals(
    settings_factory,
    actor_profile_factory,
    casting_notice_factory,
    title,
    project,
    role,
    description,
    raw_text,
):
    profile = actor_profile_factory(
        ethnicities=["Asian"],
        skills=["Mandarin Chinese", "English"],
    )
    decision = RoleScreener(settings_factory(openai_api_key=None), profile).screen(
        casting_notice_factory(
            title=title,
            project=project,
            role=role,
            location="Remote",
            compensation=None,
            description=description,
            raw_text=raw_text,
        )
    )

    assert _llm_unavailable(decision)


def _llm_unavailable(decision) -> bool:
    return (
        decision.should_apply is False
        and decision.llm_used is False
        and decision.reasons
        == [
            "Rejected because first-pass LLM screening was unavailable: no API key or call budget."
        ]
    )
