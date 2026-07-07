from __future__ import annotations

import email
import imaplib
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime

from .models import EmailMessage
from .settings import Settings


class ImapEmailClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch_messages(self, limit: int, days: int = 1) -> list[EmailMessage]:
        cutoff = datetime.now().astimezone() - timedelta(days=days)
        with imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port) as client:
            client.login(self.settings.imap_username, self.settings.imap_password)
            client.select(self.settings.imap_folder)
            status, data = client.search(
                None,
                _search_query(
                    self.settings.email_search_query,
                    cutoff,
                    self.settings.email_subject_keywords,
                ),
            )
            if status != "OK":
                raise RuntimeError(f"IMAP search failed: {status}")

            message_ids = data[0].split()[-limit:]
            messages: list[EmailMessage] = []
            for message_id in message_ids:
                fetch_status, fetch_data = client.fetch(message_id, "(RFC822)")
                if fetch_status != "OK" or not fetch_data:
                    continue
                raw = fetch_data[0][1]
                parsed = email.message_from_bytes(raw)
                message = _to_email_message(parsed)
                if _is_within_window(message.received_at, cutoff) and _subject_matches(
                    message.subject,
                    self.settings.email_subject_keywords,
                ):
                    messages.append(message)
            return messages


def _search_query(base_query: str, cutoff: datetime, subject_keywords: list[str] | None = None) -> str:
    date_text = cutoff.strftime("%d-%b-%Y")
    trimmed = base_query.strip()
    if trimmed.startswith("(") and trimmed.endswith(")"):
        trimmed = trimmed[1:-1].strip()
    subject_parts = " ".join(f'SUBJECT "{keyword}"' for keyword in subject_keywords or [])
    if subject_parts:
        trimmed = f"{trimmed} {subject_parts}"
    return f'({trimmed} SINCE "{date_text}")'


def _is_within_window(received_at: datetime | None, cutoff: datetime) -> bool:
    if received_at is None:
        return True
    if received_at.tzinfo is None:
        received_at = received_at.astimezone()
    return received_at >= cutoff


def _subject_matches(subject: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    subject_lower = subject.lower()
    return all(keyword.lower() in subject_lower for keyword in keywords)


def _to_email_message(message: Message) -> EmailMessage:
    html = ""
    text = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = part.get("Content-Disposition", "")
            if "attachment" in disposition:
                continue
            payload = _decode_payload(part)
            if content_type == "text/html":
                html += payload
            elif content_type == "text/plain":
                text += payload
    else:
        payload = _decode_payload(message)
        if message.get_content_type() == "text/html":
            html = payload
        else:
            text = payload

    return EmailMessage(
        message_id=message.get("Message-ID", ""),
        subject=_decode_header(message.get("Subject", "")),
        sender=_decode_header(message.get("From", "")),
        received_at=_parse_date(message.get("Date")),
        html=html,
        text=text,
    )


def _decode_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _decode_header(value: str) -> str:
    return str(make_header(decode_header(value)))


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
