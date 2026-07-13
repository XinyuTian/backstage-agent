from __future__ import annotations

import json
import re

from openai import OpenAI

from .models import ActorProfile, ApplicationDraft, ScreeningDecision
from .settings import Settings


class ApplicationService:
    def __init__(self, settings: Settings, profile: ActorProfile):
        self.settings = settings
        self.profile = profile
        self.dry_run = settings.dry_run
        self._client = _cover_letter_client(settings)

    def create_or_submit(self, decision: ScreeningDecision) -> ApplicationDraft:
        cover_note = ""
        if _requires_cover_letter(decision):
            try:
                cover_note = self._cover_note(decision)
            except RuntimeError as exc:
                return ApplicationDraft(
                    notice=decision.notice,
                    cover_note="",
                    dry_run=self.dry_run,
                    status="blocked_cover_letter_llm_unavailable",
                    blocker_reason=str(exc),
                )

        status = "drafted"
        blocker_reason = ""
        if not self.dry_run:
            status = "blocked_no_live_adapter"
            blocker_reason = (
                "Automatic Backstage submission is not available in the current "
                "local runner. Submit manually or use an approved interactive browser session."
            )
        return ApplicationDraft(
            notice=decision.notice,
            cover_note=cover_note,
            dry_run=self.dry_run,
            status=status,
            blocker_reason=blocker_reason,
        )

    def generate_cover_letter(self, decision: ScreeningDecision) -> ApplicationDraft:
        try:
            cover_note = self._cover_note(decision)
        except RuntimeError as exc:
            return ApplicationDraft(
                notice=decision.notice,
                cover_note="",
                dry_run=self.dry_run,
                status="blocked_cover_letter_llm_unavailable",
                blocker_reason=str(exc),
            )
        return ApplicationDraft(
            notice=decision.notice,
            cover_note=cover_note,
            dry_run=self.dry_run,
            status="drafted",
        )

    def failed_attempt(self, decision: ScreeningDecision, reason: str) -> ApplicationDraft:
        cover_note = ""
        if _requires_cover_letter(decision):
            try:
                cover_note = self._cover_note(decision)
            except RuntimeError:
                cover_note = ""
        return ApplicationDraft(
            notice=decision.notice,
            cover_note=cover_note,
            dry_run=self.dry_run,
            status="failed_application_attempt",
            blocker_reason=reason,
        )

    def _cover_note(self, decision: ScreeningDecision) -> str:
        if self._client is None:
            raise RuntimeError(
                "Cover letter LLM unavailable: missing API key for configured reviewer provider."
            )
        try:
            token_limit_param = (
                {"max_completion_tokens": 350}
                if self.settings.reviewer_provider.strip().lower() == "openai"
                else {"max_tokens": 350}
            )
            response = self._client.chat.completions.create(
                model=self.settings.reviewer_model,
                temperature=0.3,
                **token_limit_param,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You write short casting cover letters for Backstage applications. "
                            "Return plain text only. Do not use markdown. Do not invent facts, "
                            "credits, availability, contact details, training, or comfort levels. "
                            "Use only the actor profile and casting notice. Keep the tone polite, "
                            "warm, short, direct, professional, and human. Default greeting is "
                            "'Dear Casting Team,' unless a specific recipient is provided. Avoid "
                            "hype, exaggeration, and unsupported claims. Integrate the role's "
                            "requirements with the actor's relevant truthful experience or profile "
                            "details. If a requirement is a comfort boundary, mention comfort only "
                            "when the actor profile explicitly supports it. Do not include contact "
                            "details or phrases like 'best way to reach me'; Backstage handles "
                            "contact. Keep it concise."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "actor_profile": _actor_profile_for_cover_letter(self.profile),
                                "casting_notice": _casting_notice_for_cover_letter(decision),
                                "screening_reasons": decision.reasons,
                                "screening_concerns": decision.concerns,
                                "cover_letter_style": self.profile.attributes.get(
                                    "cover_letter_style",
                                    "",
                                ),
                                "instructions": (
                                    "Draft the cover letter as editable plain text. "
                                    "Use four to seven short lines or paragraphs. "
                                    "Do not include phone, email, or contact instructions."
                                ),
                            },
                            default=str,
                        ),
                    },
                ],
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Cover letter LLM failed: {exc.__class__.__name__}: {exc}") from exc
        content = response.choices[0].message.content or ""
        cover_note = content.strip()
        if not cover_note:
            raise RuntimeError("Cover letter LLM returned an empty draft.")
        return cover_note


def _cover_letter_client(settings: Settings) -> OpenAI | None:
    provider = settings.reviewer_provider.strip().lower()
    if provider == "openai":
        return OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
    if provider in {"ai_builder", "aibuilder"}:
        if not settings.ai_builder_api_key:
            return None
        return OpenAI(
            api_key=settings.ai_builder_api_key,
            base_url=settings.ai_builder_base_url,
        )
    raise ValueError(f"Unsupported REVIEWER_PROVIDER: {settings.reviewer_provider}")


def _actor_profile_for_cover_letter(profile: ActorProfile) -> dict:
    attributes = profile.attributes
    return {
        "region": attributes.get("profile_location") or _broad_region(profile.location),
        "age_range": profile.age_range,
        "genders": profile.genders,
        "ethnicities": profile.ethnicities,
        "union_status": profile.union_status,
        "relevant_skills": profile.skills,
        "preferred_role_types": profile.preferred_roles,
        "selected_comfort_attributes": {
            key: value
            for key, value in attributes.items()
            if key.startswith("comfortable_with_")
        },
        "style": attributes.get("cover_letter_style", ""),
    }


def _casting_notice_for_cover_letter(decision: ScreeningDecision) -> dict:
    notice = decision.notice
    return {
        "title": notice.title,
        "project": notice.project,
        "role": notice.role,
        "compensation": notice.compensation,
        "description": _strip_contact_instruction(notice.description),
        "shooting_locations": notice.shooting_locations,
        "shooting_dates": notice.shooting_dates,
        "screening_reasons": decision.reasons,
        "screening_concerns": decision.concerns,
    }


def _broad_region(location: str) -> str:
    lower = location.lower()
    if "bay area" in lower or "fremont" in lower or "san francisco" in lower:
        return "San Francisco Bay Area"
    return location


def _strip_contact_instruction(text: str | None) -> str | None:
    if not text:
        return text
    lines = []
    for line in text.splitlines():
        if re.search(r"\b(best way to reach|phone|email|contact)\b", line, re.IGNORECASE):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    return cleaned or None


def _requires_cover_letter(decision: ScreeningDecision) -> bool:
    notice = decision.notice
    text = "\n".join(
        part
        for part in (
            notice.title,
            notice.description,
            notice.raw_text,
        )
        if part
    ).lower()
    return bool(
        re.search(
            r"\b("
            r"cover\s*(?:letter|note)|"
            r"coverletter|"
            r"covernote|"
            r"message\s+to\s+(?:casting|production|director|producer)|"
            r"note\s+to\s+(?:casting|production|director|producer)|"
            r"personal\s+(?:message|note)|"
            r"include .*?(?:in|with) (?:your )?(?:cover|message|note)"
            r")\b",
            text,
        )
    )
