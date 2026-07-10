from backstage_agent.models import ActorProfile, CastingNotice, ProjectNotice
from backstage_agent.project_screener import ProjectScreener, project_to_notice, with_project_role_context
from backstage_agent.settings import Settings


def _profile() -> ActorProfile:
    return ActorProfile(
        name="Actor",
        location="Fremont, CA",
        age_range="25-40",
        genders=["female"],
        ethnicities=["Asian"],
        union_status="non-union",
        skills=["theater"],
        avoid=[],
        preferred_roles=["film", "theater"],
        max_travel_miles=60,
        cover_note_template="Hello",
    )


def _settings(tmp_path) -> Settings:
    return Settings(
        imap_host="imap.example.com",
        imap_port=993,
        imap_username="user",
        imap_password="pass",
        imap_folder="INBOX",
        email_search_query="ALL",
        email_subject_keywords=[],
        openai_api_key=None,
        llm_model="deepseek-v4-pro",
        max_llm_calls_per_scan=1,
        min_match_score=0.72,
        actor_profile_path=tmp_path / "profile.json",
        database_path=tmp_path / "db.sqlite3",
        dry_run=True,
    )


def _project(description: str = "Project") -> ProjectNotice:
    return ProjectNotice(
        source_message_id="m1",
        title="Virtual Staged Reading Event",
        project_url=None,
        description=description,
        raw_text=description,
        project_key="project-key",
    )


def test_project_screener_rejects_senior_community_project_locally(tmp_path):
    project = _project(
        "A virtual staged reading for The Senior Theatre Guild, "
        "focused on the 55 and above community."
    )

    decision = ProjectScreener(_settings(tmp_path), _profile()).screen(project)

    assert decision.should_apply is False
    assert decision.llm_used is False
    assert "older/senior arts community" in decision.reasons[0]


def test_project_screener_rejects_known_virtual_staged_reading_page_signature(tmp_path):
    project = _project(
        "Virtual Staged Reading Event Casting Call | Jack Truman Productions - More Projects Auditions"
    )

    decision = ProjectScreener(_settings(tmp_path), _profile()).screen(project)

    assert decision.should_apply is False
    assert decision.llm_used is False


def test_project_gate_context_includes_role_compensation():
    project = _project("Event, Bilingual Hostesses")
    role = CastingNotice(
        source_message_id="m1",
        title="Event, Bilingual Hostesses - Hostess",
        project="Event, Bilingual Hostesses",
        role="Hostess",
        location="San Francisco, CA",
        compensation="Rate: $35/hr\nTotal pay: $840",
        description="Bilingual hostess role.",
        application_url=None,
        raw_text="Bilingual hostess role.",
        project_key="project-key",
        role_key="role-key",
    )

    notice = project_to_notice(with_project_role_context(project, [role]))

    assert "Role compensation: Rate: $35/hr\nTotal pay: $840" in notice.raw_text
