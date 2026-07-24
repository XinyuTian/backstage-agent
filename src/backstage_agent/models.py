from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class ActorProfile:
    name: str
    location: str
    age_range: str
    genders: list[str]
    ethnicities: list[str]
    union_status: str
    skills: list[str]
    avoid: list[str]
    preferred_roles: list[str]
    max_travel_miles: int
    cover_note_template: str
    bio: str = ""
    credits: list[str] = field(default_factory=list)
    training: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EmailMessage:
    message_id: str
    subject: str
    sender: str
    received_at: datetime | None
    html: str
    text: str


@dataclass(frozen=True)
class ProjectNotice:
    source_message_id: str
    title: str
    project_url: str | None
    description: str
    raw_text: str
    project_date: date | None = None
    project_labels: list[str] = field(default_factory=list)
    project_key: str = ""
    shooting_locations: str | None = None
    shooting_dates: str | None = None


@dataclass(frozen=True)
class CastingNotice:
    source_message_id: str
    title: str
    project: str | None
    role: str | None
    location: str | None
    compensation: str | None
    description: str
    application_url: str | None
    raw_text: str
    project_date: date | None = None
    project_labels: list[str] = field(default_factory=list)
    project_key: str = ""
    role_key: str = ""
    shooting_locations: str | None = None
    shooting_dates: str | None = None
