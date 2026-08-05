from __future__ import annotations

import json
import re

from openai import OpenAI

from .candidate_models import CandidateFeatures, CandidateInput
from .models import ActorProfile
from .settings import Settings


DISALLOWED_SCORE_FIELDS = {"overall_score", "score_band", "should_apply", "draft_suggestion"}
_NUMBERED_REQUIREMENT_RE = re.compile(r"^requirement_\d+$")
_AGE_RANGE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*[-–—]\s*(\d{1,2})(?!\d)")
_GENDER_PATTERNS = (
    ("Nonbinary", re.compile(r"\bnon[- ]?binary\b", re.IGNORECASE)),
    ("Female", re.compile(r"\b(?:female|woman|women)\b", re.IGNORECASE)),
    ("Male", re.compile(r"\b(?:male|man|men)\b", re.IGNORECASE)),
)
_CANONICAL_REQUIREMENT_KEYS = {
    "gender",
    "age_range",
    "ethnicity",
    "union_status",
    "location",
    "language",
    "skills",
    "availability",
    "work_authorization",
}
_OPTIONAL_LANGUAGE_RE = re.compile(r"\b(?:preferred|ideally|a plus)\b", re.IGNORECASE)


def _llm_client(settings: Settings) -> OpenAI | None:
    provider = settings.llm_provider.strip().lower()
    if provider == "openai":
        return OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
    if provider in {"ai_builder", "aibuilder"}:
        if not settings.ai_builder_api_key:
            return None
        return OpenAI(
            api_key=settings.ai_builder_api_key,
            base_url=settings.ai_builder_base_url,
        )
    raise ValueError(f"Unsupported LLM_PROVIDER: {settings.llm_provider}")


class FeatureExtractor:
    def __init__(self, settings: Settings, profile: ActorProfile):
        self.settings = settings
        self.profile = profile
        self._llm_calls = 0
        self._client = _llm_client(settings)

    def extract(self, candidate: CandidateInput) -> CandidateFeatures:
        data = self._request_features(candidate)
        clean, removed = _remove_score_fields(data)
        features = CandidateFeatures(
            role_type=clean["role_type"],
            project_type=clean["project_type"],
            requirements=clean["requirements"],
            project_signals=clean["project_signals"],
            compensation=clean["compensation"],
            uncertainty=clean["uncertainty"],
            evidence_snippets=clean["evidence_snippets"],
            raw=dict(clean),
        )
        if removed:
            features.raw["schema_warning"] = "removed disallowed scoring fields"
        return features

    def _request_features(self, candidate: CandidateInput) -> dict:
        if self._client is None:
            raise ValueError("feature extraction unavailable: no LLM client configured")
        if self._llm_calls >= self.settings.max_llm_calls_per_scan:
            raise ValueError("feature extraction unavailable: LLM call budget exhausted")
        last_error = None
        for attempt in range(2):
            if self._llm_calls >= self.settings.max_llm_calls_per_scan:
                raise ValueError("feature extraction unavailable: LLM call budget exhausted")
            self._llm_calls += 1
            response = self._client.chat.completions.create(
                model=self.settings.llm_model,
                messages=[
                    {"role": "system", "content": _feature_prompt(attempt)},
                    {
                        "role": "user",
                        "content": json.dumps(_feature_request_payload(candidate, self.profile), default=str),
                    },
                ],
                response_format={"type": "json_object"},
            )
            try:
                return json.loads(response.choices[0].message.content)
            except json.JSONDecodeError as exc:
                last_error = exc
        raise last_error or ValueError("feature extraction returned invalid JSON")


def _remove_score_fields(data: dict) -> tuple[dict, bool]:
    if not isinstance(data, dict):
        raise ValueError("feature extraction payload must be a JSON object")
    clean = dict(data)
    removed = False
    for field in DISALLOWED_SCORE_FIELDS:
        if field in clean:
            clean.pop(field)
            removed = True
    clean["requirements"] = _normalize_requirements(clean.get("requirements"))
    clean["project_signals"] = _normalize_fact_dict(clean.get("project_signals"))
    clean["compensation"] = _normalize_fact_dict(clean.get("compensation"))
    clean["uncertainty"] = _normalize_fact_dict(clean.get("uncertainty"))
    clean["evidence_snippets"] = _normalize_evidence_snippets(clean.get("evidence_snippets"))
    _validate_required_fields(clean)
    return clean, removed


def _normalize_requirements(value: object) -> dict:
    if isinstance(value, dict):
        requirement_map = dict(value)
    elif isinstance(value, list):
        requirement_map = {}
        for index, item in enumerate(value, start=1):
            if isinstance(item, dict):
                key = str(
                    item.get("key")
                    or item.get("requirement_key")
                    or item.get("name")
                    or item.get("label")
                    or f"requirement_{index}"
                )
                requirement_map[_requirement_key(key)] = dict(item)
            elif isinstance(item, str) and item.strip():
                requirement_map[_requirement_key(item)] = {
                    "required": True,
                    "evidence": item.strip(),
                }
    else:
        return value  # type: ignore[return-value]
    return _normalize_requirement_map(requirement_map)


def _normalize_requirement_map(value: dict[str, object]) -> dict[str, dict]:
    normalized: dict[str, dict] = {}
    for raw_key, raw_value in value.items():
        key = _requirement_key(str(raw_key))
        entry = _normalize_requirement_entry(raw_value)
        if _NUMBERED_REQUIREMENT_RE.match(key):
            for semantic_key, semantic_entry in _split_numbered_requirement(
                key, entry
            ).items():
                if semantic_key not in normalized:
                    normalized[semantic_key] = semantic_entry
            continue
        if key in _CANONICAL_REQUIREMENT_KEYS or key.startswith(
            ("language_", "skill_")
        ):
            entry.setdefault("required", True)
            entry.setdefault("certainty", "explicit")
        normalized[key] = entry
    return normalized


def _normalize_requirement_entry(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        return {"value": value.strip(), "required": True, "evidence": value.strip()}
    if isinstance(value, list):
        evidence = "; ".join(str(item) for item in value if str(item).strip())
        return {"value": evidence, "required": True, "evidence": evidence}
    return {"value": str(value), "required": True, "evidence": str(value)}


def _split_numbered_requirement(key: str, entry: dict) -> dict[str, dict]:
    text = _requirement_text(entry)
    evidence = _requirement_evidence(entry) or text
    required_was_explicit = "required" in entry
    required = bool(entry.get("required")) if required_was_explicit else True
    if _OPTIONAL_LANGUAGE_RE.search(text):
        required = False

    split: dict[str, dict] = {}
    residual = text
    for gender, pattern in _GENDER_PATTERNS:
        match = pattern.search(residual)
        if not match:
            continue
        split["gender"] = {
            "value": gender,
            "required": required,
            "evidence": evidence,
            "certainty": "explicit",
        }
        residual = pattern.sub(" ", residual)
        break

    age_match = _AGE_RANGE_RE.search(residual)
    if age_match:
        split["age_range"] = {
            "value": f"{age_match.group(1)}-{age_match.group(2)}",
            "required": required,
            "evidence": evidence,
            "certainty": "explicit",
        }
        residual = _AGE_RANGE_RE.sub(" ", residual)

    residual = re.sub(r"\s*[,;/|]+\s*", " ", residual)
    residual = re.sub(r"\s+", " ", residual).strip(" -–—")
    if residual:
        retained = dict(entry)
        if "value" in retained and "requirement" not in retained:
            retained["value"] = residual
        else:
            retained["requirement"] = residual
        retained["required"] = (
            bool(entry.get("required")) if required_was_explicit else False
        )
        retained["certainty"] = "ambiguous"
        split[key] = retained
    elif not split:
        retained = dict(entry)
        retained["required"] = (
            bool(entry.get("required")) if required_was_explicit else False
        )
        retained["certainty"] = "ambiguous"
        split[key] = retained
    return split


def _requirement_text(entry: dict) -> str:
    for field in ("value", "requirement"):
        value = entry.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return _requirement_evidence(entry)


def _requirement_evidence(entry: dict) -> str:
    value = entry.get("evidence")
    return value.strip() if isinstance(value, str) else ""


def _requirement_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return key[:80] or "requirement"


def _normalize_fact_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        normalized = {}
        for item in value:
            if isinstance(item, str) and item.strip():
                text = item.strip()
                if "career goal alignment" in text.lower() and "high" in text.lower():
                    normalized["career_goal_alignment"] = "high"
                elif "career goal alignment" in text.lower() and "medium" in text.lower():
                    normalized["career_goal_alignment"] = "medium"
                elif "career goal alignment" in text.lower() and "low" in text.lower():
                    normalized["career_goal_alignment"] = "low"
                else:
                    normalized[_requirement_key(text)] = True
            elif isinstance(item, dict):
                normalized.update(item)
        return normalized
    if isinstance(value, str) and value.strip():
        return {"raw": value.strip()}
    if value is None:
        return {}
    return {"raw": str(value)}


def _normalize_evidence_snippets(value: object) -> list[str]:
    if isinstance(value, list):
        snippets = []
        for item in value:
            if isinstance(item, str) and item.strip():
                snippets.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("evidence") or item.get("text") or item.get("snippet")
                if isinstance(text, str) and text.strip():
                    snippets.append(text.strip())
        return snippets
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _feature_request_payload(candidate: CandidateInput, profile: ActorProfile) -> dict:
    return {
        "candidate_type": candidate.candidate_type.value,
        "title": candidate.title,
        "notice": candidate.notice.__dict__,
        "profile_summary": {
            "location": profile.location,
            "age_range": profile.age_range,
            "genders": profile.genders,
            "ethnicities": profile.ethnicities,
            "union_status": profile.union_status,
            "skills": profile.skills,
            "avoid": profile.avoid,
            "preferred_roles": profile.preferred_roles,
            "attributes": profile.attributes,
        },
    }


def _feature_prompt(attempt: int) -> str:
    if attempt:
        return (
            _FEATURE_EXTRACTION_PROMPT
            + " Return compact valid JSON only. Do not include explanations or markdown."
        )
    return _FEATURE_EXTRACTION_PROMPT


def _validate_required_fields(data: dict) -> None:
    required = {
        "role_type",
        "project_type",
        "requirements",
        "project_signals",
        "compensation",
        "uncertainty",
        "evidence_snippets",
    }
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError("missing feature extraction fields: " + ", ".join(missing))
    _require_non_empty_string(data, "role_type")
    _require_non_empty_string(data, "project_type")
    _require_dict(data, "requirements")
    _require_dict(data, "project_signals")
    _require_dict(data, "compensation")
    _require_dict(data, "uncertainty")
    _require_list_of_strings(data, "evidence_snippets")


def _require_non_empty_string(data: dict, field: str) -> None:
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"feature extraction field {field} must be a non-empty string")


def _require_dict(data: dict, field: str) -> None:
    if not isinstance(data[field], dict):
        raise ValueError(f"feature extraction field {field} must be a dict")


def _require_list_of_strings(data: dict, field: str) -> None:
    value = data[field]
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"feature extraction field {field} must be a list of strings")


_FEATURE_EXTRACTION_PROMPT = (
    "Extract structured casting candidate features as JSON. Do not score, rank, "
    "recommend applying, or decide whether the actor should apply. Return only "
    "role_type, project_type, requirements, project_signals, compensation, "
    "uncertainty, and evidence_snippets. Use canonical requirement keys gender, "
    "age_range, ethnicity, union_status, location, language, skills, availability, "
    "and work_authorization whenever the source states them clearly. Each "
    "requirement must contain value, required, evidence, and certainty; certainty "
    "must be explicit, inferred, or ambiguous. Use required=false for preferred, "
    "ideally, or a-plus language. Never convert qualitative age language into a "
    "numeric range. Keep unclear requirements generic rather than guessing. Every "
    "important extracted requirement must include evidence from the notice."
)
