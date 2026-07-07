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
        "Skipped LLM screening because no API key or call budget was available."
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
        "Skipped LLM screening because no API key or call budget was available."
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
        "Skipped LLM screening because no API key or call budget was available."
    ]
