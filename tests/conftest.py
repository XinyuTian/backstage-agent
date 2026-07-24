import json

import pytest

from backstage_agent.models import ActorProfile, CastingNotice
from backstage_agent.settings import Settings


class FakeChatClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return _Response(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Message:
    def __init__(self, content):
        self.content = content


@pytest.fixture
def fake_chat_client_factory():
    return FakeChatClient


@pytest.fixture
def actor_profile_factory():
    def build(**overrides):
        data = {
            "name": "Actor",
            "location": "Los Angeles",
            "age_range": "25-45",
            "genders": ["female"],
            "ethnicities": ["open"],
            "union_status": "non-union",
            "skills": [],
            "avoid": [],
            "preferred_roles": [],
            "max_travel_miles": 35,
            "cover_note_template": "Hello",
        }
        data.update(overrides)
        return ActorProfile(**data)

    return build

@pytest.fixture
def settings_factory(tmp_path):
    def build(**overrides):
        data = {
            "imap_host": "imap.example.com",
            "imap_port": 993,
            "imap_username": "user",
            "imap_password": "pass",
            "imap_folder": "INBOX",
            "email_search_query": "ALL",
            "email_subject_keywords": [],
            "openai_api_key": "unused",
            "llm_model": "deepseek-v4-pro",
            "max_llm_calls_per_scan": 2,
            "actor_profile_path": tmp_path / "profile.json",
            "database_path": tmp_path / "db.sqlite3",
        }
        data.update(overrides)
        return Settings(**data)

    return build


@pytest.fixture
def casting_notice_factory():
    def build(**overrides):
        data = {
            "source_message_id": "m1",
            "title": "Play - Lead",
            "project": "Play",
            "role": "Lead",
            "location": "Los Angeles",
            "compensation": "$100",
            "description": "Lead, Female, 30-50",
            "application_url": None,
            "raw_text": "Lead, Female, 30-50",
        }
        data.update(overrides)
        return CastingNotice(**data)

    return build
