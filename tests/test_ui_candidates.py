import json
from dataclasses import asdict
from datetime import date
from html.parser import HTMLParser

import backstage_agent.ui as ui
from backstage_agent.candidate_models import CandidateFeatures
from backstage_agent.models import CastingNotice
from backstage_agent.ui import (
    _candidate_evidence_sections,
    _candidate_workbench_view,
    _correction_redirect,
    _flatten_requirements,
    _get_route,
    _post_route,
    _render_candidate_detail,
    _render_candidates_index,
    _render_readable_evidence,
    _reset_component_correction_from_params,
    _save_component_correction_from_params,
)


def _rules(role_value=15):
    return {
        "version": "test-v1",
        "component_weights": {
            "role_value": role_value,
            "logistics": 10,
        },
        "score_caps": {"missing_critical_data": 60},
        "bands": [
            {"name": "top_priority", "min": 90, "max": 100},
            {"name": "strong_candidate", "min": 75, "max": 89},
            {"name": "maybe_review", "min": 60, "max": 74},
            {"name": "low_priority", "min": 40, "max": 59},
            {"name": "not_worth_applying_today", "min": 0, "max": 39},
        ],
    }


def _row():
    return {
        "id": 1,
        "candidate_type": "role",
        "project_key": "project",
        "role_key": "role",
        "title": "Play - Lead",
        "overall_score": 23,
        "score_band": "not_worth_applying_today",
        "rank_position": 1,
        "draft_suggestion": 0,
        "scoring_version": "test-v1",
        "effective_project_date": "2026-07-24",
        "notice_json": '{"description":"Lead role text","project":"Play","role":"Lead"}',
        "features_json": '{"role_type":"scripted_acting"}',
        "requirement_match_json": "[]",
        "score_json": (
            '{"positive_drivers":["Explicit role fit"],'
            '"negative_drivers":["Compensation unknown"],'
            '"subscores":{"role_value":15,"logistics":8},'
            '"score_caps":[],'
            '"score_trace":{},'
            '"scoring_snapshot":{"version":"test-v1",'
            '"component_maxima":{"role_value":15,"logistics":10},'
            '"cap_values":{"missing_critical_data":60},'
            '"band_thresholds":{"top_priority":90,"strong_candidate":75,'
            '"maybe_review":60,"low_priority":40}}}'
        ),
    }


def _correction(component="role_value", corrected=10, saved_max=15, version="test-v1"):
    return {
        "component_name": component,
        "agent_component_score": 15 if component == "role_value" else 8,
        "corrected_component_score": corrected,
        "reason": "",
        "scoring_version": version,
        "component_max_at_correction": saved_max,
    }


def test_flatten_requirements_removes_wrappers_and_duplicate_evidence():
    requirements = {
        "requirement_1": {
            "description": "Age 18+",
            "importance": "mandatory",
            "evidence": "Background / Extra, 18+",
        },
        "requirement_2": {
            "description": "Stunt experience",
            "importance": "mandatory",
            "evidence": "Stunt experience",
        },
        "requirement_3": {},
    }

    assert _flatten_requirements(requirements) == [
        {
            "description": "Age 18+",
            "importance": "mandatory",
            "evidence": "Background / Extra, 18+",
        },
        {
            "description": "Stunt experience",
            "importance": "mandatory",
            "evidence": "",
        },
    ]
    assert _flatten_requirements(["Valid passport", {"description": "Local hire"}]) == [
        {"description": "Valid passport", "importance": "", "evidence": ""},
        {"description": "Local hire", "importance": "", "evidence": ""},
    ]


def test_flatten_requirements_uses_semantic_keys_and_omits_technical_fields():
    requirements = {
        "valid_passport": {"required": True, "evidence": "Must have one."},
        "local_hire": {"required": False, "evidence": "Los Angeles local hire."},
        "requirement_1": {"required": True, "evidence": "Must have one."},
        "empty_requirement": {"required": True},
    }

    assert _flatten_requirements(requirements) == [
        {
            "description": "Valid Passport",
            "importance": "",
            "evidence": "Must have one.",
        },
        {
            "description": "Local Hire",
            "importance": "",
            "evidence": "Los Angeles local hire.",
        },
    ]


def test_flatten_requirements_labels_inferred_and_ambiguous_certainty():
    requirements = {
        "gender": {
            "value": "Male",
            "required": False,
            "evidence": "Masculine presentation preferred.",
            "certainty": "inferred",
        },
        "requirement_1": {
            "requirement": "Young-looking",
            "required": False,
            "evidence": "Young-looking male lead",
            "certainty": "ambiguous",
        },
    }

    flattened = _flatten_requirements(requirements)

    assert flattened == [
        {
            "description": "Gender",
            "importance": "inferred",
            "evidence": "Masculine presentation preferred.",
        },
        {
            "description": "Young-looking",
            "importance": "ambiguous",
            "evidence": "Young-looking male lead",
        },
    ]


def test_readable_requirements_render_certainty_labels_and_evidence():
    html = _render_readable_evidence(
        {
            "features": {
                "requirements": {
                    "gender": {
                        "value": "Male",
                        "required": False,
                        "evidence": "Masculine presentation preferred.",
                        "certainty": "inferred",
                    },
                    "requirement_1": {
                        "requirement": "Young-looking",
                        "required": False,
                        "evidence": "Young-looking male lead",
                        "certainty": "ambiguous",
                    },
                }
            }
        }
    )

    assert "Inferred" in html
    assert "Ambiguous" in html
    assert "Masculine presentation preferred." in html
    assert "Young-looking male lead" in html


def test_scalar_requirement_map_preserves_semantic_context_in_rendered_bullets():
    requirements = {
        "age_range": "60-70",
        "gender": "Female",
        "location": "Los Angeles local hire",
        "shoot_dates": "August 12-14",
        "skills": "Fluent Mandarin",
        "union_status": "Non-union",
        "requirement_1": "Must have a valid passport",
    }

    flattened = _flatten_requirements(requirements)

    assert flattened == [
        {"description": "Age Range", "importance": "", "evidence": "60-70"},
        {"description": "Gender", "importance": "", "evidence": "Female"},
        {
            "description": "Location",
            "importance": "",
            "evidence": "Los Angeles local hire",
        },
        {
            "description": "Shoot Dates",
            "importance": "",
            "evidence": "August 12-14",
        },
        {
            "description": "Skills",
            "importance": "",
            "evidence": "Fluent Mandarin",
        },
        {
            "description": "Union Status",
            "importance": "",
            "evidence": "Non-union",
        },
        {
            "description": "Must have a valid passport",
            "importance": "",
            "evidence": "",
        },
    ]

    html = _render_readable_evidence(
        {
            "features": {"requirements": requirements},
            "notice": {},
            "requirement_matches": [],
        }
    )
    for label, value in (
        ("Age Range", "60-70"),
        ("Gender", "Female"),
        ("Location", "Los Angeles local hire"),
        ("Shoot Dates", "August 12-14"),
        ("Skills", "Fluent Mandarin"),
        ("Union Status", "Non-union"),
    ):
        assert f"<li>{label}" in html
        assert value in html
    assert "Requirement 1" not in html


def _candidate_features(**overrides):
    values = {
        "role_type": "background_extra",
        "project_type": "film",
        "requirements": {
            "age_18_plus": {
                "required": True,
                "importance": "mandatory",
                "evidence": "Background / Extra, 18+",
            },
            "stunt_experience": {
                "required": True,
                "importance": "mandatory",
                "evidence": "Stunt experience a must.",
            },
        },
        "project_signals": {},
        "compensation": {"amount": "$100", "type": "flat_rate"},
        "uncertainty": {},
        "evidence_snippets": ["Stunt experience a must."],
        "raw": {},
    }
    values.update(overrides)
    return asdict(CandidateFeatures(**values))


def _casting_notice(**overrides):
    values = {
        "source_message_id": "message-1",
        "title": "The Legend of Bro-Man - Enemy Soldier",
        "project": "The Legend of Bro-Man",
        "role": "Enemy Soldier",
        "location": "Los Angeles, CA",
        "compensation": "$100 flat rate",
        "description": "Performs as one of the enemy soldiers.",
        "application_url": "https://example.test/apply",
        "raw_text": "Complete original listing.",
        "shooting_locations": "Los Angeles and Pasadena",
        "shooting_dates": "August 12-14",
    }
    values.update(overrides)
    return asdict(CastingNotice(**values))


def test_candidate_evidence_sections_are_readable_and_source_grounded():
    view = {
        "candidate_type": "role",
        "notice": _casting_notice(),
        "features": _candidate_features(),
        "requirement_matches": [
            {
                "requirement_key": "stunt_experience",
                "status": "unknown",
                "local_value": "not recorded",
                "evidence": "Stunt experience a must.",
                "reason": "Profile has no stunt experience evidence.",
            }
        ],
    }

    sections = _candidate_evidence_sections(view)
    headings = [section["heading"] for section in sections]
    text = json.dumps(sections)

    assert headings == [
        "Role",
        "Project",
        "Where and when",
        "Compensation",
        "Requirements",
        "Decision notes",
    ]
    for expected in (
        "Performs as one of the enemy soldiers.",
        "Film",
        "Los Angeles and Pasadena",
        "August 12-14",
        "$100",
        "Age 18 Plus",
        "Stunt Experience",
        "Profile has no stunt experience evidence.",
    ):
        assert expected in text
    assert "requirement_1" not in text
    assert "Requirement 1" not in text
    assert "Project Signals" not in text
    assert "Uncertainty" not in text
    assert text.count("Stunt experience a must.") == 2
    by_heading = {section["heading"]: section["items"] for section in sections}
    assert by_heading["Role"][0] == {
        "label": "Description",
        "value": "Performs as one of the enemy soldiers.",
    }
    assert by_heading["Project"] == [{"label": "Type", "value": "Film"}]


def test_candidate_evidence_sections_routes_project_only_description_to_project():
    view = {
        "candidate_type": "project_only",
        "notice": _casting_notice(
            title="Independent action-comedy short",
            project="Independent action-comedy short",
            role=None,
            location=None,
            compensation=None,
            description="Independent action-comedy short.",
            raw_text="Independent action-comedy short.",
            shooting_locations=None,
            shooting_dates=None,
        ),
        "features": _candidate_features(
            role_type="project_only",
            requirements={},
            compensation={},
            evidence_snippets=[],
        ),
        "requirement_matches": [],
    }

    sections = _candidate_evidence_sections(view)
    by_heading = {section["heading"]: section["items"] for section in sections}

    assert "Role" not in by_heading
    assert by_heading["Project"] == [
        {"label": "Description", "value": "Independent action-comedy short."},
        {"label": "Type", "value": "Film"},
    ]


def test_candidate_evidence_sections_omits_empty_payload_without_unknown_sections():
    assert _candidate_evidence_sections({}) == []
    assert _candidate_evidence_sections(
        {"notice": {}, "features": {}, "requirement_matches": []}
    ) == []


def test_render_readable_evidence_uses_adaptive_single_column_sections():
    view = {
        "candidate_type": "role",
        "notice": _casting_notice(),
        "features": _candidate_features(),
        "requirement_matches": [
            {
                "requirement_key": "stunt_experience",
                "status": "unknown",
                "reason": "Profile has no stunt experience evidence.",
            },
            {
                "requirement_key": "requirement_1",
                "status": "unknown_needs_user_input",
                "reason": "No local rule exists.",
            },
        ],
    }

    html = _render_readable_evidence(view)

    assert 'class="readable-evidence"' in html
    assert 'class="evidence-section"' in html
    for heading in (
        "Role",
        "Project",
        "Where and when",
        "Compensation",
        "Requirements",
        "Decision notes",
    ):
        assert heading in html
    assert "Original listing text" in html
    assert "<details" in html
    assert "Requirement 1" not in html
    assert "Requirement Key" not in html
    assert 'class="evidence-grid"' not in html


def test_decision_notes_preserve_adversarial_detail_text_without_reparsing():
    reason = "Schedule conflict: unavailable Aug 12; passport status: expired"
    evidence = "Agent note: <verified> & ready; keep: punctuation"
    local_value = "Known: no; source: profile & notes"
    view = {
        "candidate_type": "role",
        "notice": _casting_notice(),
        "features": _candidate_features(),
        "requirement_matches": [
            {
                "requirement_key": "availability",
                "status": "not_met",
                "local_value": local_value,
                "evidence": evidence,
                "reason": reason,
            }
        ],
    }

    sections = _candidate_evidence_sections(view)
    decision = next(
        section for section in sections if section["heading"] == "Decision notes"
    )
    assert decision["items"] == [
        {
            "label": "Availability",
            "details": [
                {"label": "Status", "value": "Not Met"},
                {"label": "Local value", "value": local_value},
                {"label": "Evidence", "value": evidence},
                {"label": "Reason", "value": reason},
            ],
        }
    ]

    html = _render_readable_evidence(view)
    assert reason in html
    assert "Known: no; source: profile &amp; notes" in html
    assert "Agent note: &lt;verified&gt; &amp; ready; keep: punctuation" in html


def test_compensation_dedupe_prefers_fuller_containing_value_and_keeps_distinct_terms():
    view = {
        "candidate_type": "role",
        "notice": _casting_notice(
            compensation="$100 flat rate (est. 8 hours); travel reimbursed"
        ),
        "features": _candidate_features(
            compensation={
                "amount": "$100",
                "type": "flat_rate",
                "details": "$100 flat rate (est. 8 hours)",
                "additional_terms": "Meals provided",
            }
        ),
        "requirement_matches": [],
    }

    sections = _candidate_evidence_sections(view)
    compensation = next(
        section for section in sections if section["heading"] == "Compensation"
    )

    assert compensation["items"] == [
        {
            "label": "Listing terms",
            "value": "$100 flat rate (est. 8 hours); travel reimbursed",
        },
        {"label": "Additional Terms", "value": "Meals provided"},
    ]


def test_render_readable_evidence_sections_are_direct_vertical_siblings():
    class EvidenceStructureParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.readable_depth = None
            self.section_parent_depths = []

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if (
                tag == "div"
                and attributes.get("class") == "readable-evidence"
            ):
                self.readable_depth = len(self.stack)
            elif (
                tag == "section"
                and attributes.get("class") == "evidence-section"
            ):
                self.section_parent_depths.append(len(self.stack))
            self.stack.append(tag)

        def handle_endtag(self, tag):
            if self.stack:
                self.stack.pop()

    parser = EvidenceStructureParser()
    parser.feed(
        _render_readable_evidence(
            {
                "candidate_type": "role",
                "notice": _casting_notice(
                    role="Lead",
                    description="Lead role.",
                ),
                "features": _candidate_features(),
            }
        )
    )

    assert len(parser.section_parent_depths) >= 2
    assert parser.section_parent_depths == [
        parser.readable_depth + 1
    ] * len(parser.section_parent_depths)


def test_render_readable_evidence_omits_empty_sections_and_original_text():
    html = _render_readable_evidence(
        {"notice": {}, "features": {}, "requirement_matches": []}
    )

    assert 'class="readable-evidence"' in html
    assert 'class="evidence-section"' not in html
    assert "Original listing text" not in html
    assert "<details" not in html


class FakeStore:
    def __init__(self, rows=None, corrections=None):
        self.rows = [_row()] if rows is None else rows
        self.corrections = corrections or []
        self.saved = None
        self.deleted = None

    def search_candidate_workbench_rows(
        self,
        query="",
        band="all",
        date_end="",
        days=1,
        limit=200,
    ):
        self.query = query
        self.band = band
        self.date_end = date_end
        self.days = days
        return self.rows

    def corrections_for_candidate_keys(self, keys):
        return {key: list(self.corrections) for key in keys}

    def upsert_candidate_correction(self, correction):
        self.saved = correction
        return 9

    def delete_candidate_correction(self, *key):
        self.deleted = key
        return True


def test_candidate_routes_exclude_legacy_dashboard_actions():
    assert _get_route("/") == ("redirect", "/candidates")
    assert _get_route("/candidates") == ("candidates", None)
    assert _post_route("/candidate-correction") == "candidate_correction"
    assert _post_route("/candidate-correction/reset") == "candidate_correction_reset"
    assert (
        _post_route("/candidate-correction/reconfirm")
        == "candidate_correction_reconfirm"
    )
    assert _post_route("/candidate-feedback") is None


def test_workbench_view_overlays_active_component_correction():
    view = _candidate_workbench_view(
        _row(),
        [_correction(corrected=10)],
        _rules(),
    )

    assert view["components"]["role_value"]["display_score"] == 10
    assert view["components"]["role_value"]["active"] is True
    assert view["agent_pre_cap_total"] == 23
    assert view["display_pre_cap_total"] == 18
    assert view["display_overall"] == 18
    assert view["agent_overall"] == 23


def test_workbench_view_marks_changed_maximum_stale():
    row = _row()
    row["scoring_version"] = "new-v2"
    row["score_json"] = row["score_json"].replace(
        '"component_maxima":{"role_value":15',
        '"component_maxima":{"role_value":20',
    ).replace('"version":"test-v1"', '"version":"new-v2"')
    view = _candidate_workbench_view(
        row,
        [_correction(corrected=10, saved_max=15, version="old-v1")],
        _rules(role_value=20),
    )

    assert view["components"]["role_value"]["stale"] is True
    assert view["components"]["role_value"]["display_score"] == 15
    assert view["agent_pre_cap_total"] == 23
    assert view["display_pre_cap_total"] == 23
    assert view["display_overall"] == 23


def test_incompatible_legacy_candidate_keeps_official_display_score():
    row = _row()
    score_payload = json.loads(row["score_json"])
    score_payload.pop("scoring_snapshot")
    score_payload["score_caps"] = ["missing_critical_data"]
    score_payload["subscores"] = {"role_value": 80, "logistics": 10}
    row["score_json"] = json.dumps(score_payload)
    row["scoring_version"] = "old-v0"
    row["overall_score"] = 23
    row["score_band"] = "not_worth_applying_today"

    view = _candidate_workbench_view(row, [], _rules())

    assert view["correction_enabled"] is False
    assert view["display_overall"] == 23
    assert view["display_band"] == "not_worth_applying_today"


def test_render_candidates_index_shows_english_workbench():
    html = _render_candidates_index(
        FakeStore(corrections=[_correction()]),
        {"id": ["1"]},
        rules=_rules(),
    )

    assert 'class="score-workbench"' in html
    assert 'class="candidate-list"' in html
    assert 'class="evidence-pane"' in html
    assert 'class="score-pane"' in html
    assert "Play — Lead" in html
    assert 'class="correction-grid"' in html
    assert "Agent score" in html
    assert "Your correction" in html
    assert "Pre-cap total" in html
    assert "data-pre-cap-total" in html
    assert (
        "pane.querySelector('[data-pre-cap-total]').textContent = preCapTotal;"
        in html
    )
    assert (
        "pane.closest('.candidate-detail').querySelector('[data-overall]').textContent"
        " = overall;"
        in html
    )
    assert "pane.querySelector('[data-overall]')" not in html
    assert "document.querySelector('[data-pre-cap-total]')" not in html
    assert "document.querySelector('[data-overall]')" not in html
    assert "Reset" in html
    assert "Human score" not in html
    assert 'lang="en"' in html


def test_overall_preview_target_and_score_pane_share_candidate_detail_wrapper():
    class DetailParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.detail_depth = 0
            self.overall_in_detail = False
            self.score_pane_in_detail = False

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            classes = set(attributes.get("class", "").split())
            if "candidate-detail" in classes:
                self.detail_depth += 1
            elif self.detail_depth and "score-pane" in classes:
                self.score_pane_in_detail = True
                self.detail_depth += 1
            elif self.detail_depth and tag == "section":
                self.detail_depth += 1
            elif self.detail_depth and "data-overall" in attributes:
                self.overall_in_detail = True

        def handle_endtag(self, tag):
            if tag == "section" and self.detail_depth:
                self.detail_depth -= 1

    parser = DetailParser()
    parser.feed(
        _render_candidates_index(
            FakeStore(corrections=[_correction()]),
            {"id": ["1"]},
            rules=_rules(),
        )
    )

    assert parser.overall_in_detail is True
    assert parser.score_pane_in_detail is True


def test_render_candidates_index_includes_accessible_workbench_divider():
    html = _render_candidates_index(
        FakeStore(),
        {"id": ["1"]},
        rules=_rules(),
    )

    assert 'class="workbench-divider"' in html
    assert 'role="separator"' in html
    assert 'aria-orientation="vertical"' in html
    assert 'tabindex="0"' in html
    assert "--candidate-list-width: 22%" in html
    assert "minmax(220px, var(--candidate-list-width))" in html
    assert "minmax(480px, 1fr)" in html
    assert html.index('class="candidate-list"') < html.index(
        'class="workbench-divider"'
    )
    assert html.index('class="workbench-divider"') < html.index(
        'class="candidate-detail"'
    )


def test_render_candidates_index_includes_divider_resize_interactions():
    html = _render_candidates_index(
        FakeStore(),
        {"id": ["1"]},
        rules=_rules(),
    )

    assert "pointerdown" in html
    assert "pointermove" in html
    assert "pointerup" in html
    assert "setPointerCapture" in html
    assert "ArrowLeft" in html
    assert "ArrowRight" in html
    assert '"Home"' in html
    assert '"End"' in html
    assert "220" in html
    assert "480" in html


def test_divider_resize_lifecycle_reclamps_and_cleans_up_pointer_capture():
    html = _render_candidates_index(
        FakeStore(),
        {"id": ["1"]},
        rules=_rules(),
    )

    assert "const synchronizeDivider = () =>" in html
    assert "adjustedLeftWidth = setLeftWidth(adjustedLeftWidth)" in html
    assert "new ResizeObserver(synchronizeDivider)" in html
    assert "resizeObserver.observe(workbench)" in html
    assert "divider.addEventListener('lostpointercapture', finishResize)" in html
    assert "divider.classList.remove('active')" in html
    assert "activePointer = null" in html


def test_divider_uses_content_bounds_and_preserves_default_until_user_resize():
    html = _render_candidates_index(
        FakeStore(),
        {"id": ["1"]},
        rules=_rules(),
    )

    assert "const contentWidth = workbench.clientWidth" in html
    assert "contentWidth - minimumRight - divider.offsetWidth" in html
    assert "event.clientX - rect.left" in html
    assert "let userAdjusted = false" in html
    assert "let adjustedLeftWidth = null" in html
    assert "if (userAdjusted)" in html
    assert "setLeftWidth(adjustedLeftWidth)" in html
    assert "workbench.style.removeProperty('--candidate-list-width')" in html


def test_workbench_filter_controls_and_links_preserve_date_context():
    store = FakeStore(corrections=[_correction()])
    html = _render_candidates_index(
        store,
        {"q": ["summer"], "date": ["2026-07-23"], "days": ["1"]},
        rules=_rules(),
    )

    assert "<h1>Backstage Candidates</h1>" in html
    assert "Ranked mutual-selection scores and calibration feedback" not in html
    assert 'placeholder="Search project or role"' in html
    assert ">Search<" not in html
    assert ">Date<" not in html
    assert "Today" in html
    assert "7 days" in html
    assert 'aria-label="Previous day"' in html
    assert 'aria-label="Next day"' in html
    assert store.date_end == "2026-07-23"
    assert store.days == 1
    assert "date=2026-07-23" in html
    assert "days=1" in html
    assert 'name="date" value="2026-07-23"' in html
    assert 'name="days" value="1"' in html


def test_date_navigation_uses_filter_button_style_and_literal_arrow_text():
    html = _render_candidates_index(
        FakeStore(),
        {"date": ["2026-07-23"], "days": ["1"]},
        rules=_rules(),
    )

    assert 'aria-label="Previous day">&lt;</a>' in html
    assert 'aria-label="Next day">&gt;</a>' in html
    assert "←" not in html
    assert "→" not in html
    assert html.count('class="date-nav"') == 4
    assert "button, .date-nav { background: #284d3d; color: white; cursor: pointer; }" in html
    assert (
        ".date-nav { border: 1px solid #b9b3a7; border-radius: 7px; "
        "padding: 8px 10px; font: inherit; text-decoration: none; }"
        in html
    )


def test_seven_day_control_toggles_window_and_preserves_filter_context():
    one_day_html = _render_candidates_index(
        FakeStore(),
        {"q": ["summer"], "date": ["2026-07-23"], "days": ["1"]},
        rules=_rules(),
    )
    seven_day_html = _render_candidates_index(
        FakeStore(),
        {"q": ["summer"], "date": ["2026-07-23"], "days": ["7"]},
        rules=_rules(),
    )

    assert (
        'href="/candidates?q=summer&amp;band=all&amp;date=2026-07-23&amp;days=7"'
        in one_day_html
    )
    assert 'aria-pressed="false">7 days</a>' in one_day_html
    assert (
        'href="/candidates?q=summer&amp;band=all&amp;date=2026-07-23&amp;days=1"'
        in seven_day_html
    )
    assert 'aria-pressed="true">7 days</a>' in seven_day_html


def test_date_filter_context_normalizes_invalid_values():
    store = FakeStore()
    html = _render_candidates_index(
        store,
        {"date": ["not-a-date"], "days": ["30"]},
        rules=_rules(),
    )

    today = date.today().isoformat()
    assert store.date_end == today
    assert store.days == 1
    assert f'name="date" value="{today}"' in html

    seven_day_store = FakeStore()
    _render_candidates_index(
        seven_day_store,
        {"date": ["2026-07-23"], "days": ["7"]},
        rules=_rules(),
    )
    assert seven_day_store.date_end == "2026-07-23"
    assert seven_day_store.days == 7


def test_date_filter_rejects_non_hyphenated_and_week_iso_forms():
    today = date.today().isoformat()
    for raw_date in ("20260723", "2026-W30-4"):
        store = FakeStore()
        _render_candidates_index(
            store,
            {"date": [raw_date], "days": ["1"]},
            rules=_rules(),
        )
        assert store.date_end == today


def test_candidate_display_title_uses_structured_project_and_role_names():
    view = _candidate_workbench_view(_row(), [], _rules())

    assert ui._candidate_display_title(view) == "Play — Lead"

    html = _render_candidates_index(
        FakeStore(),
        {"date": ["2026-07-23"]},
        rules=_rules(),
    )
    assert html.count("Play — Lead") == 2
    assert "Play - Lead" not in html


def test_candidate_display_title_preserves_unrecognized_title():
    view = _candidate_workbench_view(_row(), [], _rules())
    view["title"] = "Standalone Project"
    view["notice"] = {}

    assert ui._candidate_display_title(view) == "Standalone Project"


def test_correction_redirect_preserves_filter_context():
    location = _correction_redirect(
        {
            "candidate_id": ["1"],
            "q": ["summer"],
            "date": ["2026-07-23"],
            "days": ["7"],
        },
        "saved",
    )

    assert "q=summer" in location
    assert "date=2026-07-23" in location
    assert "days=7" in location


def test_workbench_does_not_render_nested_forms():
    class FormNestingParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.form_depth = 0
            self.max_form_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag == "form":
                self.form_depth += 1
                self.max_form_depth = max(self.max_form_depth, self.form_depth)

        def handle_endtag(self, tag):
            if tag == "form":
                self.form_depth -= 1

    parser = FormNestingParser()
    parser.feed(
        _render_candidates_index(
            FakeStore(corrections=[_correction()]),
            {"id": ["1"]},
            rules=_rules(),
        )
    )

    assert parser.max_form_depth == 1


def test_candidate_detail_renders_readable_evidence_and_correction_grid():
    row = _row()
    score_payload = json.loads(row["score_json"])
    score_payload.pop("scoring_snapshot")
    row["score_json"] = json.dumps(score_payload)
    view = _candidate_workbench_view(row, [], _rules())

    html = _render_candidate_detail(
        view,
        query="summer",
        band="all",
        date_end="2026-07-23",
        days=7,
    )

    assert "Play — Lead" in html
    assert 'class="detail-score"' in html
    assert 'class="evidence-pane"' in html
    assert 'class="readable-evidence"' in html
    assert "Role" in html
    assert "Original listing text" in html
    assert "Extracted features" not in html
    assert "Requirement matches" not in html
    assert 'class="evidence-grid"' not in html
    assert 'class="correction-grid"' in html
    assert "Agent score" in html
    assert "Your correction" in html
    for text in (
        "Overall",
        "Low Priority",
        "This candidate predates scoring snapshots",
        "Listing",
        "Active caps",
        "No active caps",
        "Positive drivers",
        "Negative drivers",
        "Score trace",
        "Edit a Correct cell",
    ):
        assert text not in html


def test_correction_grid_has_component_columns_and_exactly_two_data_rows():
    class TableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_grid = False
            self.section = ""
            self.header_cells = 0
            self.body_rows = 0
            self.body_cells = []
            self.current_body_cells = 0

        def handle_starttag(self, tag, attrs):
            attributes = dict(attrs)
            if tag == "table" and attributes.get("class") == "correction-grid":
                self.in_grid = True
            elif self.in_grid and tag in ("thead", "tbody"):
                self.section = tag
            elif self.in_grid and self.section == "thead" and tag in ("th", "td"):
                self.header_cells += 1
            elif self.in_grid and self.section == "tbody" and tag == "tr":
                self.current_body_cells = 0
            elif self.in_grid and self.section == "tbody" and tag in ("th", "td"):
                self.current_body_cells += 1

        def handle_endtag(self, tag):
            if self.in_grid and self.section == "tbody" and tag == "tr":
                self.body_rows += 1
                self.body_cells.append(self.current_body_cells)
            elif self.in_grid and tag in ("thead", "tbody"):
                self.section = ""
            elif self.in_grid and tag == "table":
                self.in_grid = False

    view = _candidate_workbench_view(_row(), [_correction()], _rules())
    parser = TableParser()
    parser.feed(
        _render_candidate_detail(
            view,
            query="summer",
            band="all",
            date_end="2026-07-23",
            days=7,
        )
    )

    expected_cells = len(view["components"]) + 2
    assert parser.header_cells == expected_cells
    assert parser.body_rows == 2
    assert parser.body_cells == [expected_cells, expected_cells]


def test_render_candidates_index_handles_empty_results():
    html = _render_candidates_index(FakeStore(rows=[]), {}, rules=_rules())

    assert "No candidates match the current filters." in html


def test_correction_input_enables_feedback_without_stealing_focus():
    html = _render_candidates_index(
        FakeStore(corrections=[_correction()]),
        {"id": ["1"]},
        rules=_rules(),
    )

    assert "feedback.disabled = false;" in html
    assert "feedback.focus()" not in html
    assert html.count("event.currentTarget.form.requestSubmit();") == 1
    assert "pane.querySelectorAll('.correction-input, .feedback-input')" in html


def test_save_component_correction_uses_persisted_identity_and_optional_reason():
    store = FakeStore()

    correction_id = _save_component_correction_from_params(
        store,
        {
            "candidate_id": ["1"],
            "component_name": ["role_value"],
            "corrected_score": ["10"],
            "reason": [""],
        },
        rules=_rules(),
    )

    assert correction_id == 9
    assert store.saved.project_key == "project"
    assert store.saved.role_key == "role"
    assert store.saved.corrected_component_score == 10
    assert store.saved.reason == ""


def test_save_component_correction_rejects_unknown_or_out_of_range_values():
    store = FakeStore()
    for component, value, message in (
        ("unknown", "5", "unknown component"),
        ("role_value", "16", "between 0 and 15"),
        ("role_value", "15", "Use Reset"),
    ):
        try:
            _save_component_correction_from_params(
                store,
                {
                    "candidate_id": ["1"],
                    "component_name": [component],
                    "corrected_score": [value],
                },
                rules=_rules(),
            )
        except ValueError as exc:
            assert message in str(exc)
        else:
            raise AssertionError("expected ValueError")


def test_reset_component_correction_uses_stable_identity():
    store = FakeStore()

    assert _reset_component_correction_from_params(
        store,
        {"candidate_id": ["1"], "component_name": ["role_value"]},
        rules=_rules(),
    )
    assert store.deleted == ("role", "project", "role", "role_value")
