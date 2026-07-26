import json
from datetime import date
from html.parser import HTMLParser

import backstage_agent.ui as ui
from backstage_agent.ui import (
    _candidate_workbench_view,
    _correction_redirect,
    _get_route,
    _post_route,
    _render_candidate_detail,
    _render_candidates_index,
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
    assert "Reset" in html
    assert "Human score" not in html
    assert 'lang="en"' in html


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


def test_candidate_detail_renders_only_compact_evidence_and_correction_grid():
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
    assert "Extracted features" in html
    assert "Requirement matches" in html
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

    expected_cells = len(view["components"]) + 1
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
