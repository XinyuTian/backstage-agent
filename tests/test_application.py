import json

from backstage_agent.application import ApplicationService
from backstage_agent.models import ActorProfile, CastingNotice, ScreeningDecision
from backstage_agent.settings import Settings


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeCompletions:
    def __init__(self):
        self.kwargs = None
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self.kwargs = kwargs
        return FakeResponse(
            "Dear Casting Team,\n\n"
            "I'd love to be considered for Extra in Room Tone.\n\n"
            "I'm reliable, easy to work with, and comfortable with the scene requirements.\n\n"
            "Thank you very much for your consideration.\n\n"
            "Best,\nXinyu Tian"
        )


class FakeChat:
    def __init__(self):
        self.completions = FakeCompletions()


class FakeClient:
    def __init__(self):
        self.chat = FakeChat()


def _settings(tmp_path, ai_builder_api_key="key") -> Settings:
    return Settings(
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
        ai_builder_api_key=ai_builder_api_key,
        reviewer_provider="ai_builder",
        reviewer_model="deepseek-v4-pro",
    )


def _profile() -> ActorProfile:
    return ActorProfile(
        name="Xinyu Tian",
        location="Fremont, CA",
        age_range="25-40",
        genders=["female"],
        ethnicities=["Asian"],
        union_status="non-union",
        skills=["Improvisation", "live unscripted comedy", "scripted theater"],
        avoid=["explicit nudity"],
        preferred_roles=["film", "commercial"],
        max_travel_miles=60,
        cover_note_template="Do not use this template.",
        attributes={
            "comfortable_with_kissing": "true",
            "cover_letter_style": (
                "Use polite, warm, short, direct plain text. Avoid hype and unsupported claims."
            ),
        },
    )


def _decision() -> ScreeningDecision:
    notice = CastingNotice(
        source_message_id="m1",
        title="Room Tone - Extra",
        project="Room Tone",
        role="Extra",
        location=None,
        compensation="$25 flat rate",
        description=(
            "Background / Extra, 18-40. Must be comfortable with kissing lead actor "
            "for opening montage. Include best way to reach you in cover letter."
        ),
        application_url="https://example.com",
        raw_text=(
            "Room Tone\nExtra\nBackground / Extra, 18-40\n"
            "Must be comfortable with kissing lead actor for opening montage.\n"
            "Include best way to reach you in cover letter."
        ),
    )
    return ScreeningDecision(
        notice=notice,
        score=0.85,
        should_apply=True,
        reasons=["Age range overlaps.", "Comfortable with kissing."],
        concerns=[],
        llm_used=True,
    )


def test_cover_note_uses_llm_prompt_with_style_profile_and_role(tmp_path, monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(
        "backstage_agent.application._cover_letter_client",
        lambda settings: fake_client,
    )

    draft = ApplicationService(_settings(tmp_path), _profile()).create_or_submit(_decision())

    assert draft.status == "drafted"
    assert draft.cover_note.startswith("Dear Casting Team,")
    kwargs = fake_client.chat.completions.kwargs
    assert kwargs["model"] == "deepseek-v4-pro"
    prompt = "\n".join(message["content"] for message in kwargs["messages"])
    assert "polite, warm, short, direct" in prompt
    assert "Room Tone" in prompt
    assert "comfortable_with_kissing" in prompt
    assert "San Francisco Bay Area" in prompt
    assert "Fremont" not in prompt
    assert "Xinyu Tian" not in prompt
    assert "https://example.com" not in prompt
    assert "source_message_id" not in prompt
    assert "raw_text" not in prompt
    assert "Do not use this template." not in prompt
    payload = json.loads(kwargs["messages"][1]["content"])
    assert "best way to reach" not in json.dumps(payload["casting_notice"])


def test_cover_note_blocks_when_llm_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "backstage_agent.application._cover_letter_client",
        lambda settings: None,
    )

    draft = ApplicationService(_settings(tmp_path, ai_builder_api_key=None), _profile()).create_or_submit(
        _decision()
    )

    assert draft.cover_note == ""
    assert draft.status == "blocked_cover_letter_llm_unavailable"
    assert "Cover letter LLM unavailable" in draft.blocker_reason


def test_cover_note_is_empty_when_cover_letter_not_required(tmp_path, monkeypatch):
    fake_client = FakeClient()
    monkeypatch.setattr(
        "backstage_agent.application._cover_letter_client",
        lambda settings: fake_client,
    )
    notice = CastingNotice(
        source_message_id="m1",
        title="Commercial - Background Actor",
        project="Commercial",
        role="Background Actor",
        location=None,
        compensation="$100 flat rate",
        description="Background actor, 25-40. No dialogue.",
        application_url="https://example.com",
        raw_text="Commercial\nBackground Actor\nBackground actor, 25-40. No dialogue.",
    )
    decision = ScreeningDecision(
        notice=notice,
        score=0.85,
        should_apply=True,
        reasons=["Age range overlaps."],
    )

    draft = ApplicationService(_settings(tmp_path), _profile()).create_or_submit(decision)

    assert draft.status == "drafted"
    assert draft.cover_note == ""
    assert fake_client.chat.completions.calls == 0
