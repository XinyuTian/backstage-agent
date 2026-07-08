from backstage_agent.models import ActorProfile, CastingNotice
from backstage_agent.screener import RoleScreener
from backstage_agent.settings import Settings


def test_local_screener_rejects_avoid_terms(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-35",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=["improv"],
        avoid=["explicit nudity"],
        preferred_roles=["commercial"],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Role",
        project=None,
        role=None,
        location=None,
        compensation=None,
        description="Contains explicit nudity",
        application_url=None,
        raw_text="Contains explicit nudity",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.score == 0
    assert decision.concerns == ["explicit nudity"]


def test_local_screener_does_not_reject_unpaid_roles_when_profile_allows_them(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-35",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=["improv"],
        avoid=["unreimbursed travel expenses"],
        preferred_roles=["film"],
        max_travel_miles=35,
        cover_note_template="Hello",
        attributes={"comfortable_with_unpaid_roles": "true"},
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="That Night at Trixies - Sierra",
        project="That Night at Trixies",
        role="Sierra",
        location=None,
        compensation="Unpaid",
        description="Supporting, 20-25. Improv-friendly short film role.",
        application_url=None,
        raw_text="Short Film\nSierra\nSupporting, Female, 20-25\nImprov-friendly role.\nUnpaid",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is True
    assert "unpaid" not in " ".join(decision.concerns).lower()


def test_local_screener_rejects_gender_mismatch_before_llm(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Lunar 5 - Dan",
        project="Lunar 5",
        role="Dan",
        location="Remote",
        compensation=None,
        description="Lead. Male, 18-50",
        application_url=None,
        raw_text="Dan\nLead. Male, 18-50",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "gender requirement" in decision.reasons[0]


def test_local_screener_rejects_male_lead_role_name_before_llm(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Behind The Confessional - Male Lead",
        project="Behind The Confessional",
        role="Male Lead",
        location=None,
        compensation=None,
        description="Lead, 18-35. A calm and emotionally layered man.",
        application_url=None,
        raw_text="Male Lead\nLead, 18-35\nA calm and emotionally layered man.",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "gender requirement" in decision.reasons[0]


def test_local_screener_rejects_male_pronoun_role_before_llm(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Lunar 5 - Shamgar",
        project="Lunar 5",
        role="Shamgar",
        location="Remote",
        compensation=None,
        description="Supporting, 18-50. A noble warrior carrying the emotional burden of his past.",
        application_url=None,
        raw_text="Shamgar\nSupporting, 18-50\nA noble warrior carrying the emotional burden of his past.",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "gender requirement" in decision.reasons[0]


def test_local_screener_rejects_male_villain_pronoun_role_before_llm(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Lunar 5 - Tristan 216",
        project="Lunar 5",
        role="Tristan 216",
        location="Remote",
        compensation=None,
        description="Lead, 20-59. His movements are mechanical. He is the villain.",
        application_url=None,
        raw_text="Tristan 216\nLead, 20-59\nHis movements are mechanical. He is the villain.",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "gender requirement" in decision.reasons[0]


def test_local_screener_rejects_required_real_singing_before_llm(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=["dance"],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
        attributes={"can_sing": "false"},
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Relive The Music - Female Singer",
        project="Relive The Music",
        role="Female Singer",
        location=None,
        compensation=None,
        description="Lead, 18+. Must be a strong vocalist with ability to harmonize.",
        application_url=None,
        raw_text="Female Singer\nLead, 18+\nMust be a strong vocalist with ability to harmonize.",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "requires real singing" in decision.reasons[0]


def test_local_screener_ignores_singing_noise_from_other_email_roles(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
        attributes={"can_sing": "false"},
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Nectar Lawyer Brunch For Two - Brunch Guests",
        project="Nectar Lawyer Brunch For Two",
        role="Brunch Guests",
        location=None,
        compensation=None,
        description="Background / Extra, 20-50. Non-speaking brunch guests.",
        application_url=None,
        raw_text="Female Singer\nLead, Female, 18+\nApply\nNectar Lawyer Brunch For Two\nBrunch Guests\nBackground / Extra, 20-50. Non-speaking brunch guests.",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert decision.reasons == [
        "Rejected because LLM screening was unavailable: no API key or call budget."
    ]


def test_local_screener_allows_singer_character_without_singing_requirement(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
        attributes={"can_sing": "false"},
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Short Film - Jazz Singer",
        project="Short Film",
        role="Jazz Singer",
        location=None,
        compensation=None,
        description="Supporting, 30-45. A retired performer in a dramatic scene. No musical performance listed.",
        application_url=None,
        raw_text="Jazz Singer\nSupporting, 30-45\nA retired performer in a dramatic scene.",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert decision.reasons == [
        "Rejected because LLM screening was unavailable: no API key or call budget."
    ]


def test_local_screener_keeps_overlapping_age_for_llm(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["open"],
        union_status="non-union",
        skills=[],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Behind the Confessional - Zella Marchand",
        project="Behind the Confessional",
        role="Zella Marchand",
        location="Worldwide",
        compensation=None,
        description="Lead. Female, 18-35",
        application_url=None,
        raw_text="Zella Marchand\nLead. Female, 18-35",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert decision.reasons == [
        "Rejected because LLM screening was unavailable: no API key or call budget."
    ]


def test_local_screener_rejects_nonmatching_identity_language_signals(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["Asian"],
        union_status="non-union",
        skills=["Mandarin Chinese", "English"],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key="unused",
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Tejidos - Adriana Nava",
        project="Tejidos",
        role="Adriana Nava",
        location="San Francisco",
        compensation=None,
        description="Supporting. Female, 35-50",
        application_url=None,
        raw_text="Tejidos\nAdriana Nava\nSupporting. Female, 35-50",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "identity or language signals" in decision.reasons[0]


def test_local_screener_allows_matching_identity_language_signals(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["Asian"],
        union_status="non-union",
        skills=["Mandarin Chinese", "English"],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Family Drama - Mei",
        project="Family Drama",
        role="Mei",
        location="Remote",
        compensation=None,
        description="Lead. Female, 18-35. Mandarin speaker.",
        application_url=None,
        raw_text="Mei\nLead. Female, 18-35. Mandarin speaker.",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.llm_used is False
    assert decision.reasons == [
        "Rejected because LLM screening was unavailable: no API key or call budget."
    ]


def test_local_screener_does_not_reject_open_role_for_project_title_only(tmp_path):
    profile = ActorProfile(
        name="Actor",
        location="Los Angeles",
        age_range="25-45",
        genders=["female"],
        ethnicities=["Asian"],
        union_status="non-union",
        skills=["Mandarin Chinese", "English"],
        avoid=[],
        preferred_roles=[],
        max_travel_miles=35,
        cover_note_template="Hello",
    )
    settings = Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="gpt-4o-mini",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Tejidos - Nurse",
        project="Tejidos",
        role="Nurse",
        location="San Francisco",
        compensation=None,
        description="Supporting. Female, 30-45",
        application_url=None,
        raw_text="Tejidos\nNurse\nSupporting. Female, 30-45",
    )

    decision = RoleScreener(settings, profile).screen(notice)

    assert decision.llm_used is False
    assert decision.reasons == [
        "Rejected because LLM screening was unavailable: no API key or call budget."
    ]
