from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from .identifiers import project_key as build_project_key
from .identifiers import role_key as build_role_key
from .models import CastingNotice, ProjectNotice
from .parser import _looks_like_role_detail
from .project_labels import extract_backstage_project_labels


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
    page_text = BeautifulSoup(html or "", "html.parser").get_text("\n", strip=True)
    project_labels = project.project_labels or extract_backstage_project_labels(page_text)
    shooting_locations, shooting_dates = _project_shooting_info(html, page_text)
    project = _with_project_info(project, shooting_locations, shooting_dates)
    project_key = project.project_key or build_project_key(
        project.title,
        project.project_url,
        project.project_date,
    )
    embedded_roles = _parse_embedded_roles(project, html)
    if embedded_roles:
        return [_with_project_labels(role, project_labels) for role in embedded_roles]

    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
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
                f"Shooting locations: {project.shooting_locations}" if project.shooting_locations else None,
                f"Shooting dates: {project.shooting_dates}" if project.shooting_dates else None,
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
                project_labels=project_labels,
                project_key=project_key,
                role_key=build_role_key(
                    project_key,
                    project.project_url,
                    role_name,
                    f"{project.title} - {role_name}",
                    description,
                ),
                shooting_locations=project.shooting_locations,
                shooting_dates=project.shooting_dates,
            )
        )
        index = next_index

    return roles


def _with_project_info(
    project: ProjectNotice,
    shooting_locations: str | None,
    shooting_dates: str | None,
) -> ProjectNotice:
    if project.shooting_locations == shooting_locations and project.shooting_dates == shooting_dates:
        return project
    return ProjectNotice(
        source_message_id=project.source_message_id,
        title=project.title,
        project_url=project.project_url,
        description=project.description,
        raw_text=project.raw_text,
        project_date=project.project_date,
        project_labels=project.project_labels,
        project_key=project.project_key,
        shooting_locations=shooting_locations or project.shooting_locations,
        shooting_dates=shooting_dates or project.shooting_dates,
    )


def _with_project_labels(notice: CastingNotice, labels: list[str]) -> CastingNotice:
    if notice.project_labels == labels:
        return notice
    return CastingNotice(
        source_message_id=notice.source_message_id,
        title=notice.title,
        project=notice.project,
        role=notice.role,
        location=notice.location,
        compensation=notice.compensation,
        description=notice.description,
        application_url=notice.application_url,
        raw_text=notice.raw_text,
        project_date=notice.project_date,
        project_labels=labels,
        project_key=notice.project_key,
        role_key=notice.role_key,
        shooting_locations=notice.shooting_locations,
        shooting_dates=notice.shooting_dates,
    )


def _parse_embedded_roles(project: ProjectNotice, html: str) -> list[CastingNotice]:
    roles_data = _embedded_roles_data(html)
    roles: list[CastingNotice] = []
    for role in roles_data:
        name = role.get("name")
        if not name:
            continue
        application_url = role.get("url") or project.project_url
        project_key = project.project_key or build_project_key(
            project.title,
            project.project_url,
            project.project_date,
        )
        role_type = role.get("role_type_display") or _role_type(role.get("role_type"))
        gender = _gender_display(role)
        age_range = role.get("age_range_display") or _age_display(role)
        role_summary = ", ".join(part for part in [role_type, gender, age_range] if part)
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
                f"Shooting locations: {project.shooting_locations}" if project.shooting_locations else None,
                f"Shooting dates: {project.shooting_dates}" if project.shooting_dates else None,
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
                application_url=application_url,
                raw_text=raw_text,
                project_date=project.project_date,
                project_labels=project.project_labels,
                project_key=project_key,
                role_key=build_role_key(
                    project_key,
                    application_url,
                    name,
                    f"{project.title} - {name}",
                    description,
                ),
                shooting_locations=project.shooting_locations,
                shooting_dates=project.shooting_dates,
            )
        )
    return roles


def _project_shooting_info(html: str, page_text: str) -> tuple[str | None, str | None]:
    data_locations, data_dates = _embedded_project_shooting_info(html)
    text_locations, text_dates = _text_project_shooting_info(page_text)
    return data_locations or text_locations, data_dates or text_dates


def _embedded_project_shooting_info(html: str) -> tuple[str | None, str | None]:
    locations = _embedded_value_lists(
        html,
        (
            "production_locations",
            "shooting_locations",
        ),
    )
    dates = _embedded_value_lists(
        html,
        (
            "production_dates",
            "shooting_dates",
        ),
    )
    production_info = _join_values(_embedded_value_lists(html, ("production_info",)))
    return (
        _join_values(locations) or _location_from_production_info(production_info),
        _join_values(dates) or production_info,
    )


def _location_from_production_info(production_info: str | None) -> str | None:
    if not production_info:
        return None
    match = re.search(
        r"\bin\s+([A-Z][A-Za-z .'-]+,\s*[A-Z]{2})(?:\s*\(|[.;,]|$)",
        production_info,
    )
    if match:
        return match.group(1).strip()
    return None


def _embedded_value_lists(html: str, keys: tuple[str, ...]) -> list[str]:
    values: list[str] = []
    for key in keys:
        pattern = re.compile(rf'"{re.escape(key)}"\s*:\s*', re.S)
        for match in pattern.finditer(html):
            value_start = match.end()
            while value_start < len(html) and html[value_start].isspace():
                value_start += 1
            if value_start >= len(html):
                continue
            if html.startswith("null", value_start):
                continue
            if html[value_start] == "[":
                value = _balanced_json_array(html, value_start)
                if not value:
                    continue
                try:
                    parsed = json.loads(value)
                except json.JSONDecodeError:
                    continue
                values.extend(_flatten_json_text(parsed))
            elif html[value_start] == '"':
                value_end = value_start + 1
                escape = False
                while value_end < len(html):
                    char = html[value_end]
                    if escape:
                        escape = False
                    elif char == "\\":
                        escape = True
                    elif char == '"':
                        break
                    value_end += 1
                try:
                    parsed = json.loads(html[value_start : value_end + 1])
                except json.JSONDecodeError:
                    continue
                values.extend(_flatten_json_text(parsed))
    return values


def _flatten_json_text(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_flatten_json_text(item))
        return result
    if isinstance(value, dict):
        preferred = [
            value.get("display_name"),
            value.get("name"),
            value.get("city"),
            value.get("state"),
            value.get("country"),
            value.get("formatted"),
            value.get("date"),
            value.get("start_date"),
            value.get("end_date"),
        ]
        direct = [str(item).strip() for item in preferred if item]
        if direct:
            return [", ".join(dict.fromkeys(direct))]
        result: list[str] = []
        for item in value.values():
            result.extend(_flatten_json_text(item))
        return result
    return []


def _join_values(values: list[str]) -> str | None:
    cleaned = []
    for value in values:
        text = re.sub(r"\s+", " ", value).strip(" ,.;")
        if text and text.lower() not in {item.lower() for item in cleaned}:
            cleaned.append(text)
    return "; ".join(cleaned) if cleaned else None


def _text_project_shooting_info(page_text: str) -> tuple[str | None, str | None]:
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    start = _index_after(lines, "dates & locations")
    if start is None:
        return None, None
    section: list[str] = []
    for line in lines[start:]:
        lower = line.lower()
        if lower in STOP_LINES or lower in {"roles in this project", "compensation & contract"}:
            break
        section.append(line.rstrip("."))
    if not section:
        return None, None
    date_lines = [line for line in section if _looks_like_date_or_schedule(line)]
    location_lines = [line for line in section if line not in date_lines]
    if not location_lines and section:
        location_lines = section[:1]
    return _join_values(location_lines), _join_values(date_lines)


def _looks_like_date_or_schedule(text: str) -> bool:
    lower = text.lower()
    if re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b", lower):
        return True
    if re.search(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", lower):
        return True
    return any(word in lower for word in ("shoots", "films", "records", "rehears", "date", "dates"))


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


def _gender_display(role: dict) -> str | None:
    values = _flatten_json_text(
        [
            role.get("gender_display"),
            role.get("gender"),
            role.get("genders"),
            role.get("gender_identities"),
        ]
    )
    genders = []
    for value in values:
        for part in re.split(r"[,/|;]+", value):
            text = part.strip()
            if not text:
                continue
            lower = text.lower()
            if lower in {"m", "male", "men", "man"}:
                genders.append("Male")
            elif lower in {"f", "female", "women", "woman"}:
                genders.append("Female")
            elif lower in {"non-binary", "nonbinary", "non binary"}:
                genders.append("Non-Binary")
            elif lower in {"gender-nonconforming", "gender nonconforming"}:
                genders.append("Gender-Nonconforming")
            elif lower in {"any", "all", "open"}:
                genders.append("Open")
            elif "male" in lower and "female" not in lower:
                genders.append("Male")
            elif "female" in lower:
                genders.append("Female")
    return ", ".join(dict.fromkeys(genders)) or None


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
