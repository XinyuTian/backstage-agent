from __future__ import annotations

import json
from dataclasses import asdict

from openai import OpenAI

from .models import ActorProfile, CastingNotice, ReviewDecision
from .settings import Settings


class DecisionReviewer:
    def __init__(self, settings: Settings, profile: ActorProfile):
        self.settings = settings
        self.profile = profile
        self._calls = 0
        self._client = _reviewer_client(settings)

    def review(self, notice: CastingNotice) -> ReviewDecision:
        if self._client is None:
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=["Reviewer unavailable: missing API key for configured provider."],
                model=self.settings.reviewer_model,
            )
        if self._calls >= self.settings.max_reviewer_calls_per_scan:
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=["Reviewer unavailable: reviewer call budget was exhausted."],
                model=self.settings.reviewer_model,
            )
        return self._llm_review(notice)

    def _llm_review(self, notice: CastingNotice) -> ReviewDecision:
        self._calls += 1
        try:
            token_limit_param = (
                {"max_completion_tokens": 1000}
                if self.settings.reviewer_provider.strip().lower() == "openai"
                else {"max_tokens": 1000}
            )
            response = self._client.chat.completions.create(
                model=self.settings.reviewer_model,
                temperature=0,
                response_format={"type": "json_object"},
                **token_limit_param,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the strict second-pass reviewer for casting applications. "
                            "You must make an independent decision using only the actor profile "
                            "and casting notice. You are not given, and must not infer, the first "
                            "model's reasoning. Return compact JSON with fields: status, score, "
                            "reasons, concerns. status must be one of approved, rejected, hold. "
                            "Approve only when the actor is a clear fit. Reject when the role has "
                            "a concrete conflict with the actor profile, especially real singing "
                            "requirements when can_sing is false, voiceover/native English needs, "
                            "or ethnicity/race/language/cultural signals that do not match. Hold "
                            "when the application requires unanswered questions or unlisted skills, "
                            "availability, wardrobe, comfort level, or special abilities. Do not "
                            "reject solely because gender is ambiguous; ambiguity may mean there is "
                            "no gender constraint. Treat age ranges as compatible when they overlap "
                            "at even one age; actor age range 25-40 overlaps role age range 20-25 "
                            "because both include 25, so that is not an age conflict. "
                            "Do not reject horror by itself when comfortable_with_horror is true. "
                            "Do not reject unpaid roles or list unpaid compensation as a concern "
                            "when comfortable_with_unpaid_roles is true. Treat unreimbursed travel "
                            "expenses as different from an unpaid role."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "actor_profile": asdict(self.profile),
                                "casting_notice": asdict(notice),
                                "minimum_score": self.settings.min_match_score,
                            },
                            default=str,
                        ),
                    },
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=[f"Reviewer API failed: {exc.__class__.__name__}: {exc}"],
                model=self.settings.reviewer_model,
            )

        content = response.choices[0].message.content or "{}"
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=["Reviewer returned invalid JSON."],
                concerns=[content[:500]],
                model=self.settings.reviewer_model,
            )

        status = str(data.get("status", "")).strip().lower()
        if status not in {"approved", "rejected", "hold"}:
            status = "hold"
        score = float(data.get("score", 0.0))
        if status == "approved" and score < self.settings.min_match_score:
            status = "hold"
        return ReviewDecision(
            notice=notice,
            status=status,
            score=score,
            reasons=list(data.get("reasons", [])),
            concerns=list(data.get("concerns", [])),
            model=self.settings.reviewer_model,
        )


def _reviewer_client(settings: Settings) -> OpenAI | None:
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
