from __future__ import annotations

import json
from dataclasses import asdict

from openai import OpenAI

from .decision_core import (
    DecisionBucket,
    StructuredReview,
    resolve_final_bucket,
    should_draft_bucket,
)
from .models import ActorProfile, CastingNotice, ReviewDecision
from .settings import Settings

REVIEWER_ALLOWED_PREFERENCES = (
    "Do not reject projects or roles because they require active Instagram tagging "
    "when the actor profile has comfortable_with_active_instagram_tagging=true."
)


class DecisionReviewer:
    def __init__(self, settings: Settings, profile: ActorProfile):
        self.settings = settings
        self.profile = profile
        self._calls = 0
        self._client = _reviewer_client(settings)

    def review(
        self,
        notice: CastingNotice,
        initial_bucket: str | None = None,
        classifier_json: dict | None = None,
    ) -> ReviewDecision:
        return self._review_with_prompt(
            notice,
            _ROLE_REVIEWER_PROMPT,
            initial_bucket=initial_bucket,
            classifier_json=classifier_json,
        )

    def review_project(
        self,
        notice: CastingNotice,
        initial_bucket: str | None = None,
        classifier_json: dict | None = None,
    ) -> ReviewDecision:
        return self._review_with_prompt(
            notice,
            _PROJECT_REVIEWER_PROMPT,
            initial_bucket=initial_bucket,
            classifier_json=classifier_json,
        )

    def _review_with_prompt(
        self,
        notice: CastingNotice,
        system_prompt: str,
        initial_bucket: str | None = None,
        classifier_json: dict | None = None,
    ) -> ReviewDecision:
        if self._client is None:
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=["Reviewer unavailable: missing API key for configured provider."],
                model=self.settings.reviewer_model,
                final_bucket=DecisionBucket.READY_FOR_REVIEW.value,
                reviewer_impact="reviewer_unavailable",
            )
        if self._calls >= self.settings.max_reviewer_calls_per_scan:
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=["Reviewer unavailable: reviewer call budget was exhausted."],
                model=self.settings.reviewer_model,
                final_bucket=DecisionBucket.READY_FOR_REVIEW.value,
                reviewer_impact="reviewer_unavailable",
            )
        return self._llm_review(
            notice,
            system_prompt,
            initial_bucket=initial_bucket,
            classifier_json=classifier_json,
        )

    def _llm_review(
        self,
        notice: CastingNotice,
        system_prompt: str,
        initial_bucket: str | None = None,
        classifier_json: dict | None = None,
    ) -> ReviewDecision:
        self._calls += 1
        data, error = self._request_structured_review(
            notice,
            system_prompt,
            initial_bucket=initial_bucket,
            classifier_json=classifier_json,
        )
        if data is None:
            artifacts = resolve_final_bucket(
                schema_error=error,
                base_bucket=_initial_bucket(initial_bucket),
            )
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=["Data/parse error from reviewer."],
                concerns=[error] if error else [],
                model=self.settings.reviewer_model,
                final_bucket=artifacts.final_bucket.value,
                reviewer_impact=artifacts.reviewer_impact,
                schema_error=artifacts.schema_error,
            )
        try:
            structured = StructuredReview.from_json(data)
        except ValueError as exc:
            artifacts = resolve_final_bucket(
                schema_error=f"structured review validation failed: {exc}",
                base_bucket=_initial_bucket(initial_bucket),
            )
            return ReviewDecision(
                notice=notice,
                status="error",
                score=0.0,
                reasons=["Data/parse error from reviewer."],
                concerns=[str(exc)],
                model=self.settings.reviewer_model,
                final_bucket=artifacts.final_bucket.value,
                reviewer_json=data,
                reviewer_impact=artifacts.reviewer_impact,
                schema_error=artifacts.schema_error,
            )
        artifacts = resolve_final_bucket(
            review=structured,
            base_bucket=_initial_bucket(initial_bucket),
        )
        status = "approved" if should_draft_bucket(artifacts.final_bucket) else "hold"
        return ReviewDecision(
            notice=notice,
            status=status,
            score=structured.confidence,
            reasons=structured.reasons,
            concerns=structured.concerns,
            model=self.settings.reviewer_model,
            final_bucket=artifacts.final_bucket.value,
            reviewer_json=artifacts.reviewer_json,
            reviewer_impact=artifacts.reviewer_impact,
            schema_error=artifacts.schema_error,
        )

    def _request_structured_review(
        self,
        notice: CastingNotice,
        system_prompt: str,
        initial_bucket: str | None = None,
        classifier_json: dict | None = None,
    ) -> tuple[dict | None, str]:
        last_error = ""
        for attempt in range(2):
            prompt = system_prompt
            if attempt:
                prompt = (
                    "Repair the previous response. Return only valid JSON matching "
                    "the structured reviewer schema. "
                    f"Previous error: {last_error}"
                )
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
                            "content": prompt,
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "actor_profile": asdict(self.profile),
                                    "casting_notice": asdict(notice),
                                    "minimum_score": self.settings.min_match_score,
                                    "initial_bucket": initial_bucket,
                                    "classifier_json": classifier_json,
                                },
                                default=str,
                            ),
                        },
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                return None, f"Reviewer API failed: {exc.__class__.__name__}: {exc}"
            content = response.choices[0].message.content or "{}"
            try:
                data = json.loads(content)
                StructuredReview.from_json(data)
                return data, ""
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = f"structured review validation failed: {exc}"
        return None, last_error


def _initial_bucket(value: str | None) -> DecisionBucket:
    if value:
        try:
            return DecisionBucket(value)
        except ValueError:
            pass
    return DecisionBucket.AUTO_APPLY_DRAFT


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


_ROLE_REVIEWER_PROMPT = (
    "You are the strict second-pass reviewer for casting applications. "
    "Return only JSON with fields: verdict, downgrade_to, evidence_snippets, "
    "reasons, concerns, confidence. verdict must be confirm or downgrade. "
    "downgrade_to may be ready_for_review, needs_my_preference, reject, "
    "data_parse_error, or null. You are downgrade-only: confirm when the "
    "initial bucket is supportable, and downgrade only when exact notice "
    "evidence supports the downgrade. Put that exact evidence in "
    "evidence_snippets. For auto_apply_draft, the only allowed downgrade is "
    "ready_for_review. Use needs_my_preference only for unanswered actor "
    "preferences. Use reject only for concrete conflicts with the actor "
    "profile, especially explicit gender requirements that do not match, real "
    "singing requirements when can_sing is false, native English needs, or "
    "ethnicity/race/language/cultural signals that do not match. Do not reject "
    "solely because gender is ambiguous. Treat age ranges as compatible when "
    "they overlap at even one age. "
    "Do not reject horror by itself when comfortable_with_horror is true. "
    "Do not reject unpaid roles or list unpaid compensation as a concern "
    "when comfortable_with_unpaid_roles is true. Treat unreimbursed travel "
    "expenses as different from an unpaid role. "
    f"{REVIEWER_ALLOWED_PREFERENCES}"
)

_PROJECT_REVIEWER_PROMPT = (
    "You are the strict second-pass reviewer for casting projects. "
    "You are deciding whether this whole project should proceed to role-level "
    "filtering. Return only JSON with fields: verdict, downgrade_to, "
    "evidence_snippets, reasons, concerns, confidence. verdict must be confirm "
    "or downgrade. downgrade_to may be ready_for_review, needs_my_preference, "
    "reject, data_parse_error, or null. You are downgrade-only: confirm when "
    "the initial bucket is supportable, and downgrade only when exact notice "
    "evidence supports the downgrade. Reject only concrete project-wide "
    "conflicts, especially adult or explicit content, unreimbursed travel "
    "expenses, impossible location or date requirements, project-wide native "
    "English requirements, or a poor travel/pay tradeoff. Use ready_for_review "
    "for unclear location, dates, pay, travel, safety, or application logistics. "
    "Do not reject for role-specific gender, age, ethnicity, language, singing, "
    "wardrobe, or special-skill requirements unless the notice says they apply "
    "to the entire project. Do not reject unpaid projects by itself when "
    "comfortable_with_unpaid_roles is true; consider unpaid plus distant travel "
    "as a possible conflict. "
    f"{REVIEWER_ALLOWED_PREFERENCES}"
)
