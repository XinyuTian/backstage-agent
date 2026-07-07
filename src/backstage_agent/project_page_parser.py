from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .models import CastingNotice, ProjectNotice
from .parser import _looks_like_role_detail


STOP_LINES = {
    "dates & locations",
    "compensation & contract",
    "additional:",
    "key details",
    "similar calls",
}

SKIP_LINES = {
    "roles in this project",
    "collapse all roles",
    "expand all roles",
    "actors & performers",
    "apply",
    "share",
}


def parse_project_page_roles(project: ProjectNotice, html: str) -> list[CastingNotice]:
    embedded_roles = _parse_embedded_roles(project, html)
    if embedded_roles:
        return embedded_roles

    text = BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    role_lines = _role_section(lines)
    compensation = _compensation_by_role(lines)
    location = _location(lines)
    roles: list[CastingNotice] = []
    index = 0

    while index < len(role_lines):
        line = role_lines[index]
        lower = line.lower()
        if lower in SKIP_LINES or lower.startswith("work-from-home"):
            index += 1
            continue

        detail_index = _next_role_detail_index(role_lines, index + 1)
        if detail_index is None:
            index += 1
            continue

        role_name = line
        role_detail = role_lines[detail_index]
        next_index = _next_role_start_index(role_lines, detail_index + 1)
        body_lines = [
            value
            for value in role_lines[detail_index + 1 : next_index]
            if value.lower() not in SKIP_LINES and not value.lower().startswith("work-from-home")
        ]
        description = "\n".join([role_detail, *body_lines]).strip()
        role_compensation = compensation.get(role_name.lower())
        raw_text = "\n".join(
            part
            for part in [
                project.description,
                f"Location: {location}" if location else None,
                role_name,
                description,
                role_compensation,
            ]
            if part
        )
        roles.append(
            CastingNotice(
                source_message_id=project.source_message_id,
                title=f"{project.title} - {role_name}",
                project=project.title,
                role=role_name,
                location=location,
                compensation=role_compensation,
                description=description[:3000],
                application_url=project.project_url,
                raw_text=raw_text,
                project_date=project.project_date,
            )
        )
        index = next_index

    return roles


def _parse_embedded_roles(project: ProjectNotice, html: str) -> list[CastingNotice]:
    roles_data = _embedded_roles_data(html)
    roles: list[CastingNotice] = []
    for role in roles_data:
        name = role.get("name")
        if not name:
            continue
        role_type = role.get("role_type_display") or _role_type(role.get("role_type"))
        age_range = role.get("age_range_display") or _age_display(role)
        role_summary = ", ".join(part for part in [role_type, age_range] if part)
        description = role.get("description") or ""
        compensation = "\n".join(
            part
            for part in [role.get("rate_display"), role.get("total_pay_display")]
            if part
        ) or None
        location = "Remote" if role.get("is_remote") else None
        raw_text = "\n".join(
            part
            for part in [
                project.description,
                f"Location: {location}" if location else None,
                name,
                role_summary,
                description,
                compensation,
            ]
            if part
        )
        roles.append(
            CastingNotice(
                source_message_id=project.source_message_id,
                title=f"{project.title} - {name}",
                project=project.title,
                role=name,
                location=location,
                compensation=compensation,
                description="\n".join(part for part in [role_summary, description] if part)[:3000],
                application_url=role.get("url") or project.project_url,
                raw_text=raw_text,
                project_date=project.project_date,
            )
        )
    return roles


def _embedded_roles_data(html: str) -> list[dict]:
    marker = '"roles": ['
    marker_index = html.find(marker)
    if marker_index == -1:
        return []
    array_start = html.find("[", marker_index)
    array_text = _balanced_json_array(html, array_start)
    if not array_text:
        return []
    try:
        data = json.loads(array_text)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _balanced_json_array(text: str, start: int) -> str | None:
    if start < 0 or start >= len(text) or text[start] != "[":
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _role_type(value: str | None) -> str | None:
    return {"L": "Lead", "S": "Supporting", "B": "Background"}.get(value or "")


def _age_display(role: dict) -> str | None:
    minimum = role.get("min_age")
    maximum = role.get("max_age")
    if minimum and maximum:
        return f"{minimum}-{maximum}"
    if minimum:
        return f"{minimum}+"
    return None


def _role_section(lines: list[str]) -> list[str]:
    start = _index_after(lines, "roles in this project")
    if start is None:
        return []
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].lower() in STOP_LINES:
            end = index
            break
    return lines[start:end]


def _index_after(lines: list[str], marker: str) -> int | None:
    for index, line in enumerate(lines):
        if line.lower() == marker:
            return index + 1
    return None


def _next_role_detail_index(lines: list[str], start: int) -> int | None:
    for index in range(start, min(len(lines), start + 4)):
        lower = lines[index].lower()
        if lower in SKIP_LINES or lower.startswith("work-from-home"):
            continue
        if _looks_like_role_detail(lines[index]):
            return index
        return None
    return None


def _next_role_start_index(lines: list[str], start: int) -> int:
    index = start
    while index < len(lines):
        lower = lines[index].lower()
        if lower in STOP_LINES:
            return index
        if lower in SKIP_LINES or lower.startswith(("pre-screen requests:", "rate:", "total pay:")):
            index += 1
            continue
        if _next_role_detail_index(lines, index + 1) is not None:
            return index
        index += 1
    return len(lines)


def _compensation_by_role(lines: list[str]) -> dict[str, str]:
    start = _index_after(lines, "compensation & contract")
    if start is None:
        return {}
    result: dict[str, str] = {}
    index = start
    while index < len(lines):
        line = lines[index]
        lower = line.lower()
        if lower.startswith("additional:") or lower in {"key details", "additional materials"}:
            break
        if line.endswith(": Lead") or line.endswith(": Supporting") or ":" in line:
            role = line.split(":", 1)[0].strip()
            details: list[str] = []
            cursor = index + 1
            while cursor < len(lines) and len(details) < 2:
                if ":" in lines[cursor] and not lines[cursor].lower().startswith(("rate:", "total pay:")):
                    break
                if lines[cursor].lower().startswith(("rate:", "total pay:")):
                    details.append(lines[cursor])
                cursor += 1
            if details:
                result[role.lower()] = "\n".join(details)
        index += 1
    return result


def _location(lines: list[str]) -> str | None:
    for index, line in enumerate(lines):
        if line.lower() == "dates & locations" and index + 1 < len(lines):
            return lines[index + 1].rstrip(".")
        if re.match(r"seeking talent\b", line, flags=re.I):
            return line
    return None
