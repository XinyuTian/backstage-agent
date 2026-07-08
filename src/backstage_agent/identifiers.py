from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse


def project_key_from_url(url: str | None) -> str | None:
    parts = _casting_url_parts(url)
    return parts[0] if parts else None


def role_key_from_url(url: str | None) -> str | None:
    parts = _casting_url_parts(url)
    return parts[1] if len(parts) > 1 else None


def fallback_project_key(title: str, project_date: date | None) -> str:
    prefix = project_date.isoformat() if project_date else "unknown-date"
    return f"{prefix}:{_slugify(title)}"


def fallback_role_key(project_key: str, role: str | None, title: str, description: str = "") -> str:
    role_text = role or title
    description_hint = _slugify(description[:120])
    if description_hint:
        return f"{project_key}:{_slugify(role_text)}:{description_hint}"
    return f"{project_key}:{_slugify(role_text)}"


def project_key(title: str, url: str | None, project_date: date | None) -> str:
    return project_key_from_url(url) or fallback_project_key(title, project_date)


def role_key(project_key_value: str, url: str | None, role: str | None, title: str, description: str = "") -> str:
    return role_key_from_url(url) or fallback_role_key(project_key_value, role, title, description)


def _casting_url_parts(url: str | None) -> list[str]:
    if not url:
        return []
    path_parts = [
        part
        for part in urlparse(url).path.strip("/").split("/")
        if part
    ]
    try:
        casting_index = path_parts.index("casting")
    except ValueError:
        return []
    return path_parts[casting_index + 1 :]


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "unknown"
