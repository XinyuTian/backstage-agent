from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .identifiers import project_key, role_key
from .models import CastingNotice, EmailMessage, ProjectNotice
from .project_labels import extract_backstage_project_labels


APPLICATION_WORDS = ("apply", "submit", "audition", "casting")
EMAIL_DATE_RE = re.compile(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\b")


def parse_project_notices(message: EmailMessage) -> list[ProjectNotice]:
    soup = BeautifulSoup(message.html or "", "html.parser")
    text = soup.get_text("\n", strip=True) if message.html else message.text
    chunks = _split_notice_chunks(text)
    links_by_title = _project_links_by_title(soup)
    project_date = _date_from_email_subject(message.subject, message.received_at)
    projects: list[ProjectNotice] = []
    seen: set[str] = set()

    for chunk in chunks:
        cleaned = _strip_digest_footer(_collapse_space(chunk))
        if len(cleaned) < 40 or not _is_project_chunk(cleaned):
            continue
        title = _project_title(cleaned)
        project_url = _lookup_project_link(title, links_by_title)
        key = project_key(title, project_url, project_date)
        if key in seen:
            continue
        seen.add(key)
        projects.append(
            ProjectNotice(
                source_message_id=message.message_id,
                title=title,
                project_url=project_url,
                description=cleaned[:3000],
                raw_text=cleaned,
                project_date=project_date,
                project_labels=extract_backstage_project_labels(cleaned),
                project_key=key,
            )
        )

    if projects:
        return projects

    return [
        ProjectNotice(
            source_message_id=message.message_id,
            title=notice.project or notice.title,
            project_url=notice.application_url,
            description=notice.description,
            raw_text=notice.raw_text,
            project_date=notice.project_date,
            project_labels=notice.project_labels,
            project_key=notice.project_key,
        )
        for notice in parse_casting_notices(message)
    ]


def parse_casting_notices(message: EmailMessage) -> list[CastingNotice]:
    soup = BeautifulSoup(message.html or "", "html.parser")
    text = soup.get_text("\n", strip=True) if message.html else message.text
    links = _extract_links(soup) or _extract_text_links(text)
    apply_links = _extract_apply_links(soup)
    chunks = _split_notice_chunks(text)
    project_date = _date_from_email_subject(message.subject, message.received_at)

    structured_notice = _parse_structured_notice(message, text, links, project_date)
    if structured_notice:
        return [structured_notice]

    digest_notices = _parse_digest_notices(
        message=message,
        chunks=chunks,
        links=links,
        apply_links=apply_links,
        project_date=project_date,
    )
    if digest_notices:
        return digest_notices

    notices: list[CastingNotice] = []
    for chunk in chunks:
        cleaned = _collapse_space(chunk)
        if len(cleaned) < 80:
            continue
        notices.append(
            CastingNotice(
                source_message_id=message.message_id,
                title=_first_line(cleaned) or message.subject,
                project=_field(cleaned, "Project"),
                role=_field(cleaned, "Role"),
                location=_field(cleaned, "Location"),
                compensation=_field(cleaned, "Compensation") or _field(cleaned, "Pay"),
                description=cleaned[:3000],
                application_url=_best_application_link(links),
                raw_text=cleaned,
                project_date=project_date,
                project_labels=extract_backstage_project_labels(cleaned),
                project_key=project_key(
                    _field(cleaned, "Project") or _first_line(cleaned) or message.subject,
                    _best_application_link(links),
                    project_date,
                ),
                role_key=role_key(
                    project_key(
                        _field(cleaned, "Project") or _first_line(cleaned) or message.subject,
                        _best_application_link(links),
                        project_date,
                    ),
                    _best_application_link(links),
                    _field(cleaned, "Role"),
                    _first_line(cleaned) or message.subject,
                    cleaned,
                ),
            )
        )
    return notices


def _parse_structured_notice(
    message: EmailMessage,
    text: str,
    links: list[str],
    project_date: date | None,
) -> CastingNotice | None:
    cleaned = _collapse_space(text)
    project = _field(cleaned, "Project")
    role = _field(cleaned, "Role")
    if not project and not role:
        return None
    return CastingNotice(
        source_message_id=message.message_id,
        title=f"{project} - {role}" if project and role else _first_line(cleaned) or message.subject,
        project=project,
        role=role,
        location=_field(cleaned, "Location"),
        compensation=_field(cleaned, "Compensation") or _field(cleaned, "Pay"),
        description=cleaned[:3000],
        application_url=_best_application_link(links),
        raw_text=cleaned,
        project_date=project_date,
        project_labels=extract_backstage_project_labels(cleaned),
        project_key=project_key(project or _first_line(cleaned) or message.subject, _best_application_link(links), project_date),
        role_key=role_key(
            project_key(project or _first_line(cleaned) or message.subject, _best_application_link(links), project_date),
            _best_application_link(links),
            role,
            f"{project} - {role}" if project and role else _first_line(cleaned) or message.subject,
            cleaned,
        ),
    )


def _parse_digest_notices(
    message: EmailMessage,
    chunks: list[str],
    links: list[str],
    apply_links: list[str],
    project_date: date | None,
) -> list[CastingNotice]:
    notices: list[CastingNotice] = []
    current_project_title: str | None = None
    current_project_description: str | None = None
    apply_link_index = 0

    for chunk in chunks:
        cleaned = _strip_digest_footer(_collapse_space(chunk))
        if len(cleaned) < 40:
            continue
        if cleaned.lower().startswith("seeking talent from:"):
            roles, location = _roles_from_seeking_chunk(cleaned)
        else:
            roles, location = [], None

        if not roles or not current_project_title:
            if _is_project_chunk(cleaned):
                current_project_title = _project_title(cleaned)
                current_project_description = cleaned
            continue

        for role_name, role_summary, compensation in roles:
            application_url = (
                apply_links[apply_link_index]
                if apply_link_index < len(apply_links)
                else _best_application_link(links)
            )
            apply_link_index += 1
            raw_text = "\n".join(
                part
                for part in [
                    current_project_description,
                    f"Seeking talent from: {location}" if location else None,
                    role_name,
                    role_summary,
                    compensation,
                ]
                if part
            )
            notices.append(
                # Digest fallback roles can point directly at role URLs.
                # Use the Backstage role slug when present, otherwise a deterministic text key.
                CastingNotice(
                    source_message_id=message.message_id,
                    title=f"{current_project_title} - {role_name}",
                    project=current_project_title,
                    role=role_name,
                    location=location,
                    compensation=compensation,
                    description=raw_text[:3000],
                    application_url=application_url,
                    raw_text=raw_text,
                    project_date=project_date,
                    project_labels=extract_backstage_project_labels(
                        current_project_description or raw_text
                    ),
                    project_key=project_key(current_project_title, application_url, project_date),
                    role_key=role_key(
                        project_key(current_project_title, application_url, project_date),
                        application_url,
                        role_name,
                        f"{current_project_title} - {role_name}",
                        raw_text,
                    ),
                )
            )

    return notices


def _date_from_email_subject(subject: str, received_at) -> date | None:
    match = EMAIL_DATE_RE.search(subject)
    if not match:
        return None
    year = received_at.year if received_at else date.today().year
    try:
        return datetime.strptime(f"{match.group(1)} {match.group(2)} {year}", "%b %d %Y").date()
    except ValueError:
        return None


def _extract_links(soup: BeautifulSoup) -> list[str]:
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            links.append(href)
    return links


def _extract_text_links(text: str) -> list[str]:
    return re.findall(r"https?://\\S+", text)


def _extract_apply_links(soup: BeautifulSoup) -> list[str]:
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        if anchor.get_text(" ", strip=True).lower() != "apply":
            continue
        href = anchor["href"]
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            links.append(href)
    return links


def _project_links_by_title(soup: BeautifulSoup) -> dict[str, str]:
    links: dict[str, str] = {}
    for anchor in soup.find_all("a", href=True):
        label = _normalize_project_title(anchor.get_text(" ", strip=True))
        if not label or label.lower() in {"apply", "more", "basic filter"}:
            continue
        parsed = urlparse(anchor["href"])
        if parsed.scheme in {"http", "https"}:
            links[label.lower()] = anchor["href"]
    return links


def _lookup_project_link(title: str, links_by_title: dict[str, str]) -> str | None:
    normalized = _normalize_project_title(title).lower()
    if normalized in links_by_title:
        return links_by_title[normalized]
    stripped = normalized.strip("'\"")
    for label, link in links_by_title.items():
        if label.strip("'\"") == stripped:
            return link
    return None


def _split_notice_chunks(text: str) -> list[str]:
    if not text:
        return []
    separators = re.compile(r"\n(?=(?:Project|Role|Casting|Now Casting|Seeking)\b)", re.I)
    chunks = separators.split(text)
    return chunks if len(chunks) > 1 else [text]


def _is_project_chunk(text: str) -> bool:
    return text.lower().startswith(("casting ", "now casting ")) or _posted_project_title(text) is not None


def _project_title(text: str) -> str:
    quoted = re.search(r'"([^"]+)"', text)
    if quoted:
        return _normalize_project_title(quoted.group(1))
    posted_title = _posted_project_title(text)
    if posted_title:
        return _normalize_project_title(posted_title)
    single_quoted = re.search(r"'([^']+)'", text)
    if single_quoted:
        return _normalize_project_title(single_quoted.group(1))
    first_line = _first_line(text) or "Untitled Project"
    first_line = re.sub(r"^(Casting|Now Casting)\s+", "", first_line, flags=re.I)
    return _normalize_project_title(first_line.rstrip("."))


def _normalize_project_title(title: str) -> str:
    words = title.strip(" ,.;:'\"").split()
    return " ".join(word.capitalize() if word.isupper() else word for word in words)


def _posted_project_title(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if not line.lower().startswith("posted "):
            continue
        for candidate in lines[index + 1 :]:
            lower = candidate.lower()
            if lower in {"more", "apply"} or _is_digest_metadata(candidate):
                continue
            return candidate
    return None


def _is_digest_metadata(line: str) -> bool:
    lower = line.lower()
    if lower in {
        "$ paid",
        "paid",
        "nonunion",
        "union",
        "scripted show",
        "short film",
        "feature film",
        "gigs",
        "animation",
        "backstage",
        "verify data",
        "trusted by",
    }:
        return True
    return lower.startswith(("21 new jobs", "matching your search", "edit this search", "change email frequency"))


def _roles_from_seeking_chunk(text: str) -> tuple[list[tuple[str, str | None, str | None]], str | None]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].lower().startswith("seeking talent from:"):
        return [], None

    first_line_location = lines[0].split(":", 1)[1].strip()
    location = first_line_location or (lines[1] if len(lines) > 1 else None)
    start_index = 1 if first_line_location else 2
    roles: list[tuple[str, str | None, str | None]] = []
    current_name: str | None = None
    current_details: list[str] = []

    for line in lines[start_index:]:
        lower = line.lower()
        if lower in {"more"}:
            continue
        if lower == "apply":
            if current_name:
                role = _role_tuple(current_name, current_details)
                if role:
                    roles.append(role)
                current_name = None
                current_details = []
            continue
        if lower in {"view all matching jobs"}:
            break
        if current_name is None:
            current_name = line
        else:
            current_details.append(line)

    if current_name:
        role = _role_tuple(current_name, current_details)
        if role:
            roles.append(role)

    return roles, location


def _role_tuple(name: str, details: list[str]) -> tuple[str, str | None, str | None] | None:
    if not any(_looks_like_role_detail(detail) for detail in details):
        return None
    compensation = next(
        (detail for detail in details if "pay amount" in detail.lower() or detail.lower().startswith("pay:")),
        None,
    )
    summary_parts = [detail for detail in details if detail != compensation]
    return name, "\n".join(summary_parts) if summary_parts else None, compensation


def _looks_like_role_detail(text: str) -> bool:
    lower = text.lower()
    if re.search(r"\b\d{1,2}\s*(?:-|–|to)\s*\d{1,2}\b|\b\d{1,2}\+", text):
        return True
    return lower.startswith(
        (
            "lead",
            "supporting",
            "principal",
            "background",
            "featured",
            "day player",
            "series regular",
            "recurring",
        )
    )


def _strip_digest_footer(text: str) -> str:
    footer_markers = (
        "View All Matching Jobs",
        "Get $40 for every friend",
        "You're receiving this email",
        "Receiving too many or not enough?",
    )
    cutoff = len(text)
    for marker in footer_markers:
        marker_index = text.find(marker)
        if marker_index != -1:
            cutoff = min(cutoff, marker_index)
    return text[:cutoff].strip()


def _field(text: str, label: str) -> str | None:
    match = re.search(rf"{re.escape(label)}\s*:\s*(.+)", text, flags=re.I)
    if not match:
        return None
    return match.group(1).splitlines()[0].strip()


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:180]
    return None


def _collapse_space(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _best_application_link(links: list[str]) -> str | None:
    for link in links:
        lower = link.lower()
        if any(word in lower for word in APPLICATION_WORDS):
            return link
    return links[0] if links else None
