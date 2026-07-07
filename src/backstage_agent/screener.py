from __future__ import annotations

import json
import re
from dataclasses import asdict

from openai import OpenAI

from .models import ActorProfile, CastingNotice, ScreeningDecision
from .settings import Settings


class RoleScreener:
    def __init__(self, settings: Settings, profile: ActorProfile):
        self.settings = settings
        self.profile = profile
        self._llm_calls = 0
        self._client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def screen(self, notice: CastingNotice) -> ScreeningDecision:
        local_decision = self._local_screen(notice)
        if local_decision is not None:
            return local_decision
        if self._client is None or self._llm_calls >= self.settings.max_llm_calls_per_scan:
            return ScreeningDecision(
                notice=notice,
                score=0.0,
                should_apply=False,
                reasons=["Skipped LLM screening because no API key or call budget was available."],
            )
        return self._llm_screen(notice)

    def _local_screen(self, notice: CastingNotice) -> ScreeningDecision | None:
        text = notice.raw_text.lower()
        concerns = [term for term in self.profile.avoid if term.lower() in text]
        if concerns:
            return ScreeningDecision(
                notice=notice,
                score=0.0,
                should_apply=False,
                reasons=["Rejected by actor profile avoidance rules."],
                concerns=concerns,
            )

        hard_reject_reasons = []
        role_genders = _role_genders(notice.raw_text)
        if role_genders and not _gender_matches(role_genders, self.profile.genders):
            hard_reject_reasons.append(
                f"Rejected locally: role gender requirement ({', '.join(role_genders)}) "
                f"does not match actor profile ({', '.join(self.profile.genders)})."
            )

        actor_age = _age_range(self.profile.age_range)
        role_age = _role_age_range(notice.raw_text)
        if actor_age and role_age and not _ranges_overlap(actor_age, role_age):
            hard_reject_reasons.append(
                f"Rejected locally: actor age range {self.profile.age_range} "
                f"does not overlap role age range {_format_range(role_age)}."
            )

        identity_reason = _identity_language_mismatch(notice, self.profile)
        if identity_reason:
            hard_reject_reasons.append(identity_reason)

        if hard_reject_reasons:
            return ScreeningDecision(
                notice=notice,
                score=0.0,
                should_apply=False,
                reasons=hard_reject_reasons,
                concerns=[],
            )

        preferred_hits = [
            role for role in self.profile.preferred_roles if role.lower() in text
        ]
        skill_hits = [skill for skill in self.profile.skills if skill.lower() in text]
        if len(preferred_hits) >= 2 or (preferred_hits and skill_hits):
            score = min(0.95, 0.65 + 0.1 * len(preferred_hits) + 0.05 * len(skill_hits))
            return ScreeningDecision(
                notice=notice,
                score=score,
                should_apply=score >= self.settings.min_match_score,
                reasons=[
                    "Matched local preferred-role and skill rules.",
                    f"Preferred hits: {', '.join(preferred_hits) or 'none'}.",
                    f"Skill hits: {', '.join(skill_hits) or 'none'}.",
                ],
            )
        return None

    def _llm_screen(self, notice: CastingNotice) -> ScreeningDecision:
        self._llm_calls += 1
        response = self._client.chat.completions.create(
            model=self.settings.llm_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You screen casting notices for fit. Return compact JSON with "
                        "score between 0 and 1, should_apply boolean, reasons array, "
                        "and concerns array. Be selective and cost-conscious. "
                        "Treat age ranges as compatible when they overlap at all; "
                        "for example actor 25-45 fits role 18-35. Do not reject "
                        "because the ranges are not identical. Only cite a comfort "
                        "boundary when the actor profile explicitly avoids it or an "
                        "attribute says they are not comfortable with it. If an "
                        "attribute says comfortable_with_horror is true, do not treat "
                        "horror as a concern by itself. Do not infer explicit content "
                        "from horror, romance, or mature themes unless the notice says so. "
                        "Only include concerns that are concrete conflicts or open questions "
                        "from the casting notice; do not list generic actor boundaries as "
                        "concerns when the notice does not mention them. Respect explicit "
                        "ethnicity, race, language, and cultural identity signals in the "
                        "notice; do not treat a role as a fit when those signals clearly do "
                        "not match the actor profile."
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
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        score = float(data.get("score", 0.0))
        return ScreeningDecision(
            notice=notice,
            score=score,
            should_apply=bool(data.get("should_apply", score >= self.settings.min_match_score)),
            reasons=list(data.get("reasons", [])),
            concerns=list(data.get("concerns", [])),
            llm_used=True,
        )


def _age_range(text: str) -> tuple[int, int] | None:
    match = re.search(r"\b(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\b", text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        return (min(low, high), max(low, high))
    plus = re.search(r"\b(\d{1,2})\+", text)
    if plus:
        return (int(plus.group(1)), 120)
    single = re.search(r"\b(\d{1,2})\b", text)
    if single:
        age = int(single.group(1))
        return (age, age)
    return None


def _role_age_range(text: str) -> tuple[int, int] | None:
    for line in text.splitlines():
        if _looks_like_role_line(line):
            age = _age_range(line)
            if age:
                return age
    return _age_range(text)


def _ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return max(left[0], right[0]) <= min(left[1], right[1])


def _format_range(value: tuple[int, int]) -> str:
    return f"{value[0]}+" if value[1] == 120 else f"{value[0]}-{value[1]}"


def _role_genders(text: str) -> list[str]:
    genders = []
    for line in text.splitlines():
        if not _looks_like_role_line(line):
            continue
        lower = line.lower()
        if "female" in lower:
            genders.append("female")
        if re.search(r"\bmale\b", lower):
            genders.append("male")
        if "non-binary" in lower or "nonbinary" in lower:
            genders.append("non-binary")
        if "gender-nonconforming" in lower:
            genders.append("gender-nonconforming")
        break
    lower_text = text.lower()
    if re.search(r"\b(he|him|his|father|son|brother|husband|boyfriend|king|warrior)\b", lower_text):
        genders.append("male")
    if re.search(r"\b(she|her|hers|mother|daughter|sister|wife|girlfriend|queen)\b", lower_text):
        genders.append("female")
    return list(dict.fromkeys(genders))


def _gender_matches(role_genders: list[str], profile_genders: list[str]) -> bool:
    normalized_profile = {gender.lower() for gender in profile_genders}
    if "open" in role_genders or "any" in role_genders:
        return True
    return bool(set(role_genders) & normalized_profile)


def _looks_like_role_line(line: str) -> bool:
    lower = line.lower()
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


def _identity_language_mismatch(notice: CastingNotice, profile: ActorProfile) -> str | None:
    profile_traits = _profile_identity_terms(profile)
    signals = _identity_language_signals(notice)
    mismatches = [
        signal
        for signal in signals
        if not signal["matches_any"] & profile_traits
    ]
    if not mismatches:
        return None
    labels = ", ".join(signal["label"] for signal in mismatches)
    return (
        "Rejected locally: role/project has identity or language signals "
        f"({labels}) that do not match actor profile."
    )


def _profile_identity_terms(profile: ActorProfile) -> set[str]:
    text = " ".join(
        [
            *profile.ethnicities,
            *profile.skills,
            *profile.preferred_roles,
            profile.bio,
            " ".join(profile.attributes.values()),
        ]
    ).lower()
    terms = set()
    if any(term in text for term in ["asian", "chinese", "mandarin", "east asian"]):
        terms.update({"asian", "east_asian", "chinese", "mandarin"})
    if "spanish" in text:
        terms.add("spanish")
    if any(term in text for term in ["latino", "latina", "latinx", "hispanic"]):
        terms.update({"latino", "hispanic"})
    if "black" in text or "african" in text:
        terms.update({"black", "african"})
    if "white" in text or "caucasian" in text:
        terms.update({"white", "caucasian"})
    if "middle eastern" in text or "arab" in text:
        terms.update({"middle_eastern", "arab"})
    if "south asian" in text or "indian" in text:
        terms.update({"south_asian", "indian"})
    return terms


def _identity_language_signals(notice: CastingNotice) -> list[dict[str, set[str] | str]]:
    role_text = "\n".join(part for part in [notice.role, _role_detail_line(notice.raw_text)] if part)
    role_lower = role_text.lower()
    signals: list[dict[str, set[str] | str]] = []
    patterns: list[tuple[str, tuple[str, ...], set[str]]] = [
        (
            "Spanish/Latino/Hispanic",
            ("spanish", "español", "latina", "latino", "latinx", "hispanic"),
            {"spanish", "latino", "hispanic"},
        ),
        ("Black/African", ("black", "african american", "afro-latina", "afro-latino"), {"black", "african"}),
        ("White/Caucasian", ("white", "caucasian"), {"white", "caucasian"}),
        ("Middle Eastern/Arab", ("middle eastern", "arab", "arabic"), {"middle_eastern", "arab"}),
        ("South Asian/Indian", ("south asian", "indian", "hindi", "urdu"), {"south_asian", "indian"}),
        ("East Asian/Chinese/Mandarin", ("east asian", "chinese", "mandarin"), {"asian", "east_asian", "chinese", "mandarin"}),
    ]
    for label, needles, matches_any in patterns:
        if any(re.search(rf"\b{re.escape(needle)}\b", role_lower) for needle in needles):
            signals.append({"label": label, "matches_any": matches_any})

    role = (notice.role or "").lower()
    spanish_name_tokens = {
        "adriana",
        "alejandro",
        "ana",
        "carlos",
        "carmen",
        "diego",
        "elena",
        "joci",
        "jose",
        "juan",
        "luis",
        "maria",
        "miguel",
        "nava",
        "sofia",
    }
    tokens = set(re.findall(r"[a-z]+", role))
    if tokens & spanish_name_tokens:
        signals.append({"label": "Spanish-language role name", "matches_any": {"spanish", "latino", "hispanic"}})

    return signals


def _role_detail_line(text: str) -> str | None:
    for line in text.splitlines():
        if _looks_like_role_line(line):
            return line
    return None
