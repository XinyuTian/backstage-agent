from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from .candidate_models import CandidateComponentCorrection, ScoringSnapshot
from .scoring import (
    build_scoring_snapshot,
    load_scoring_rules,
    recompute_overall_from_subscores,
)
from .settings import load_settings
from .storage import DecisionStore


def _get_route(path: str) -> tuple[str, str | None]:
    if path == "/":
        return "redirect", "/candidates"
    if path == "/candidates":
        return "candidates", None
    return "not_found", None


def _post_route(path: str) -> str | None:
    return {
        "/candidate-correction": "candidate_correction",
        "/candidate-correction/reset": "candidate_correction_reset",
        "/candidate-correction/reconfirm": "candidate_correction_reconfirm",
    }.get(path)


class DashboardServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        settings = load_settings()
        self.store = DecisionStore(settings.database_path)

    def serve_forever(self) -> None:
        store = self.store
        rules = load_scoring_rules()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                route, destination = _get_route(parsed.path)
                if route == "redirect":
                    self.send_response(303)
                    self.send_header("Location", destination or "/candidates")
                    self.end_headers()
                    return
                if route == "candidates":
                    self._send_html(
                        _render_candidates_index(
                            store,
                            parse_qs(parsed.query),
                            rules=rules,
                        )
                    )
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                action = _post_route(urlparse(self.path).path)
                if action is None:
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0") or "0")
                params = parse_qs(
                    self.rfile.read(length).decode("utf-8"),
                    keep_blank_values=True,
                )
                try:
                    if action == "candidate_correction":
                        _save_component_correction_from_params(
                            store,
                            params,
                            rules=rules,
                        )
                        status = "saved"
                    elif action == "candidate_correction_reset":
                        _reset_component_correction_from_params(
                            store,
                            params,
                            rules=rules,
                        )
                        status = "reset"
                    else:
                        _reconfirm_component_correction_from_params(
                            store,
                            params,
                            rules=rules,
                        )
                        status = "reconfirmed"
                except ValueError as exc:
                    self.send_error(400, str(exc))
                    return
                self.send_response(303)
                self.send_header("Location", _correction_redirect(params, status))
                self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send_html(self, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        print(f"Candidate UI running at http://{self.host}:{self.port}")
        server.serve_forever()


def _render_candidates_index(
    store: DecisionStore,
    params: dict[str, list[str]],
    *,
    rules: dict | None = None,
) -> str:
    current_rules = rules or load_scoring_rules()
    query = _param(params, "q")
    band = _param(params, "band", "all")
    date_end, days = _date_filter_context(params)
    rows = store.search_candidate_workbench_rows(
        query=query,
        band=band,
        date_end=date_end,
        days=days,
        limit=200,
    )
    keys = [_candidate_identity(row) for row in rows]
    correction_rows = store.corrections_for_candidate_keys(keys)
    views = [
        _candidate_workbench_view(
            row,
            correction_rows.get(_candidate_identity(row), []),
            current_rules,
        )
        for row in rows
    ]
    selected_id = _optional_int(_param(params, "id"))
    selected = next(
        (view for view in views if view["id"] == selected_id),
        views[0] if views else None,
    )
    status = _param(params, "correction")
    notice = (
        f'<p class="notice">Correction {_esc(status)}.</p>'
        if status in {"saved", "reset", "reconfirmed"}
        else ""
    )
    content = (
        _render_workbench(views, selected, query, band, date_end, days)
        if selected is not None
        else '<div class="empty">No candidates match the current filters.</div>'
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Score Review Workbench</title>
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>Backstage Candidates</h1>
    </div>
  </header>
  <main>
    {notice}
    <form class="filters" method="get" action="/candidates">
      <input name="q" value="{_esc(query)}" placeholder="Search project or role" aria-label="Search project or role">
      <input name="date" type="date" value="{_esc(date_end)}" aria-label="Date">
      {_date_navigation(query, band, date_end, days)}
      <input type="hidden" name="days" value="{days}">
      <input type="hidden" name="band" value="{_esc(band)}">
      <button type="submit">Filter</button>
    </form>
    {content}
  </main>
  <script>{_JS}</script>
</body>
</html>"""


def _candidate_workbench_view(row, corrections, current_rules: dict) -> dict:
    score_payload = _json_dict(_row_value(row, "score_json"))
    agent_subscores = _integer_dict(score_payload.get("subscores"))
    snapshot_payload = score_payload.get("scoring_snapshot")
    warnings: list[str] = []
    correction_enabled = True
    if isinstance(snapshot_payload, dict):
        snapshot = _scoring_snapshot(snapshot_payload)
    elif str(_row_value(row, "scoring_version") or "") == str(
        current_rules.get("version", "")
    ):
        snapshot = build_scoring_snapshot(current_rules)
        warnings.append(
            "This candidate predates scoring snapshots; current matching rules are used."
        )
    else:
        snapshot = _fallback_snapshot(agent_subscores)
        correction_enabled = False
        warnings.append(
            "Corrections are disabled because this candidate has no compatible scoring snapshot."
        )

    indexed_corrections = {
        str(_row_value(correction, "component_name")): correction
        for correction in corrections
    }
    merged = dict(agent_subscores)
    components = {}
    for name, maximum in snapshot.component_maxima.items():
        agent_score = int(agent_subscores.get(name, 0))
        correction = indexed_corrections.get(name)
        corrected_score = (
            int(_row_value(correction, "corrected_component_score"))
            if correction is not None
            else None
        )
        saved_max = (
            int(_row_value(correction, "component_max_at_correction"))
            if correction is not None
            else None
        )
        stale = correction is not None and saved_max != maximum
        active = correction is not None and not stale and correction_enabled
        if active and corrected_score is not None:
            merged[name] = corrected_score
        version_warning = (
            correction is not None
            and str(_row_value(correction, "scoring_version")) != snapshot.version
            and not stale
        )
        components[name] = {
            "name": name,
            "label": _humanize(name),
            "maximum": maximum,
            "agent_score": agent_score,
            "corrected_score": corrected_score,
            "display_score": merged.get(name, agent_score),
            "reason": str(_row_value(correction, "reason") or ""),
            "active": active,
            "stale": stale,
            "saved_max": saved_max,
            "version_warning": version_warning,
        }

    agent_pre_cap_total = sum(
        int(component["agent_score"]) for component in components.values()
    )
    display_pre_cap_total = sum(int(value) for value in merged.values())
    caps = [
        str(cap)
        for cap in score_payload.get("score_caps", [])
        if str(cap) in snapshot.cap_values
    ]
    if correction_enabled:
        display_overall, display_band = recompute_overall_from_subscores(
            merged,
            caps,
            snapshot,
        )
        display_band_value = display_band.value
    else:
        display_overall = int(_row_value(row, "overall_score") or 0)
        display_band_value = str(_row_value(row, "score_band") or "")
    return {
        "id": int(_row_value(row, "id")),
        "title": str(_row_value(row, "title") or "Untitled Candidate"),
        "candidate_type": str(_row_value(row, "candidate_type") or ""),
        "project_key": str(_row_value(row, "project_key") or ""),
        "role_key": str(_row_value(row, "role_key") or ""),
        "effective_project_date": str(
            _row_value(row, "effective_project_date") or ""
        ),
        "agent_overall": int(_row_value(row, "overall_score") or 0),
        "agent_band": str(_row_value(row, "score_band") or ""),
        "display_overall": display_overall,
        "display_band": display_band_value,
        "agent_pre_cap_total": agent_pre_cap_total,
        "display_pre_cap_total": display_pre_cap_total,
        "agent_rank": _row_value(row, "rank_position"),
        "agent_draft_suggestion": bool(_row_value(row, "draft_suggestion")),
        "components": components,
        "caps": [
            {"name": cap, "label": _humanize(cap), "value": snapshot.cap_values[cap]}
            for cap in caps
        ],
        "snapshot": asdict(snapshot),
        "warnings": warnings,
        "correction_enabled": correction_enabled,
        "notice": _json_dict(_row_value(row, "notice_json")),
        "features": _json_dict(_row_value(row, "features_json")),
        "requirement_matches": _json_value(
            _row_value(row, "requirement_match_json"),
            [],
        ),
        "positive_drivers": _string_list(score_payload.get("positive_drivers")),
        "negative_drivers": _string_list(score_payload.get("negative_drivers")),
        "score_trace": score_payload.get("score_trace", {}),
    }


def _save_component_correction_from_params(
    store: DecisionStore,
    params: dict[str, list[str]],
    *,
    rules: dict | None = None,
) -> int:
    return _persist_component_correction(
        store,
        params,
        rules=rules or load_scoring_rules(),
        reconfirm=False,
    )


def _reconfirm_component_correction_from_params(
    store: DecisionStore,
    params: dict[str, list[str]],
    *,
    rules: dict | None = None,
) -> int:
    return _persist_component_correction(
        store,
        params,
        rules=rules or load_scoring_rules(),
        reconfirm=True,
    )


def _persist_component_correction(
    store: DecisionStore,
    params: dict[str, list[str]],
    *,
    rules: dict,
    reconfirm: bool,
) -> int:
    candidate_id = _required_int(params, "candidate_id")
    component_name = _param(params, "component_name").strip()
    corrected_score = _required_int(params, "corrected_score")
    row = _candidate_row_by_id(store, candidate_id)
    identity = _candidate_identity(row)
    corrections = store.corrections_for_candidate_keys([identity])[identity]
    view = _candidate_workbench_view(row, corrections, rules)
    component = view["components"].get(component_name)
    if component is None:
        raise ValueError(f"unknown component: {component_name}")
    if not view["correction_enabled"]:
        raise ValueError("Corrections are disabled for this candidate.")
    if component["stale"] and not reconfirm:
        raise ValueError("Use Reconfirm for a correction with a changed maximum.")
    maximum = int(component["maximum"])
    if not 0 <= corrected_score <= maximum:
        raise ValueError(f"corrected_score must be between 0 and {maximum}")
    if corrected_score == int(component["agent_score"]):
        raise ValueError("Use Reset to return to the agent score.")
    snapshot = ScoringSnapshot(**view["snapshot"])
    correction = CandidateComponentCorrection(
        candidate_type=identity[0],
        project_key=identity[1],
        role_key=identity[2],
        candidate_id_at_submission=candidate_id,
        component_name=component_name,
        agent_component_score=int(component["agent_score"]),
        corrected_component_score=corrected_score,
        reason=_param(params, "reason").strip(),
        scoring_version=snapshot.version,
        component_max_at_correction=maximum,
    )
    return store.upsert_candidate_correction(correction)


def _reset_component_correction_from_params(
    store: DecisionStore,
    params: dict[str, list[str]],
    *,
    rules: dict | None = None,
) -> bool:
    candidate_id = _required_int(params, "candidate_id")
    component_name = _param(params, "component_name").strip()
    row = _candidate_row_by_id(store, candidate_id)
    view = _candidate_workbench_view(
        row,
        store.corrections_for_candidate_keys([_candidate_identity(row)])[
            _candidate_identity(row)
        ],
        rules or load_scoring_rules(),
    )
    if component_name not in view["components"]:
        raise ValueError(f"unknown component: {component_name}")
    return store.delete_candidate_correction(
        *_candidate_identity(row),
        component_name,
    )


def _candidate_row_by_id(store: DecisionStore, candidate_id: int):
    for row in store.search_candidate_workbench_rows(limit=1_000_000):
        if int(row["id"]) == candidate_id:
            return row
    raise ValueError(f"Candidate {candidate_id} was not found.")


def _render_workbench(
    views: list[dict],
    selected: dict,
    query: str,
    band: str,
    date_end: str,
    days: int,
) -> str:
    candidates = "".join(
        _render_candidate_list_item(
            view, selected["id"], query, band, date_end, days
        )
        for view in views
    )
    return f"""
    <section class="score-workbench">
      <nav class="candidate-list" aria-label="Candidates">{candidates}</nav>
      <div class="workbench-divider" role="separator"
        aria-orientation="vertical" aria-label="Resize candidate panels"
        aria-valuemin="220" aria-valuenow="220" aria-valuemax="220"
        tabindex="0"></div>
      <section class="candidate-detail">
        {_render_candidate_detail(selected, query, band, date_end, days)}
      </section>
    </section>
    """


def _render_candidate_list_item(
    view: dict,
    selected_id: int,
    query: str,
    band: str,
    date_end: str,
    days: int,
) -> str:
    params = urlencode(
        {
            "id": view["id"],
            "q": query,
            "band": band,
            "date": date_end,
            "days": days,
        },
    )
    selected_class = " selected" if view["id"] == selected_id else ""
    return f"""
    <a class="candidate-list-item band-{_esc(view["display_band"])}{selected_class}"
       href="/candidates?{_esc(params)}">
      <span class="list-score">{view["display_overall"]}</span>
      <span class="list-copy">
        <strong>{_esc(_candidate_display_title(view))}</strong>
        <small>{_esc(view["effective_project_date"] or "Date unknown")} · {_esc(_humanize(view["candidate_type"]))}</small>
      </span>
    </a>
    """


def _render_candidate_detail(
    view: dict,
    query: str,
    band: str,
    date_end: str,
    days: int,
) -> str:
    return f"""
      <div class="detail-heading">
        <h2>{_esc(_candidate_display_title(view))}</h2>
        <strong class="detail-score" data-overall>{view["display_overall"]}</strong>
      </div>
      <section class="evidence-pane">
        {_render_readable_evidence(view)}
      </section>
      <section class="score-pane"
        data-agent-subscores="{_esc(json.dumps({name: item["agent_score"] for name, item in view["components"].items()}))}"
        data-active-corrections="{_esc(json.dumps({name: item["corrected_score"] for name, item in view["components"].items() if item["active"]}))}"
        data-cap-values="{_esc(json.dumps([cap["value"] for cap in view["caps"]]))}">
        {_render_component_grid(view, query, date_end, days, band)}
      </section>
    """


def _render_component_grid(
    view: dict,
    query: str,
    date_end: str,
    days: int,
    band: str = "all",
) -> str:
    components = list(view["components"].values())
    headings = "".join(
        f'<th scope="col">{_esc(component["label"])}</th>'
        for component in components
    )
    headings = '<th scope="col">Pre-cap total</th>' + headings
    agent_scores = "".join(
        f'<td>{component["agent_score"]} / {component["maximum"]}</td>'
        for component in components
    )
    agent_scores = (
        f'<td data-agent-pre-cap-total>{view["agent_pre_cap_total"]}</td>'
        + agent_scores
    )
    correction_cells = "".join(
        _render_component_correction_cell(
            view, component, query, band, date_end, days
        )
        for component in components
    )
    correction_cells = (
        f'<td data-pre-cap-total>{view["display_pre_cap_total"]}</td>'
        + correction_cells
    )
    return f"""
      <div class="correction-grid-wrapper">
        <table class="correction-grid">
          <thead><tr><th></th>{headings}</tr></thead>
          <tbody>
            <tr><th scope="row">Agent score</th>{agent_scores}</tr>
            <tr><th scope="row">Your correction</th>{correction_cells}</tr>
          </tbody>
        </table>
      </div>
    """


def _render_component_correction_cell(
    view: dict,
    component: dict,
    query: str,
    band: str,
    date_end: str,
    days: int,
) -> str:
    hidden = _hidden_context(
        view["id"], component["name"], query, band, date_end, days
    )
    correction_value = (
        str(component["corrected_score"])
        if component["corrected_score"] is not None
        else ""
    )
    action = "/candidate-correction"
    button = "Save"
    if component["stale"]:
        action = "/candidate-correction/reconfirm"
        button = "Reconfirm"
    disabled = " disabled" if not view["correction_enabled"] else ""
    reason_disabled = (
        " disabled"
        if not view["correction_enabled"] or not correction_value
        else ""
    )
    reset = (
        '<button class="secondary" type="submit" '
        'formaction="/candidate-correction/reset">Reset</button>'
        if component["corrected_score"] is not None
        else ""
    )
    return f"""
      <td data-component="{_esc(component["name"])}">
        <form class="correction-form" method="post" action="{action}">
          {hidden}
          <input class="correction-input" name="corrected_score" type="number"
            min="0" max="{component["maximum"]}" value="{_esc(correction_value)}"
            aria-label="{_esc(component["label"])} correction"{disabled}>
          <input class="feedback-input" name="reason" value="{_esc(component["reason"])}"
            placeholder="Feedback" aria-label="{_esc(component["label"])} feedback"{reason_disabled}>
          <span class="actions"><button type="submit"{disabled}>{button}</button>{reset}</span>
        </form>
      </td>
    """


def _hidden_context(
    candidate_id: int,
    component_name: str,
    query: str,
    band: str,
    date_end: str,
    days: int,
) -> str:
    return (
        f'<input type="hidden" name="candidate_id" value="{candidate_id}">'
        f'<input type="hidden" name="component_name" value="{_esc(component_name)}">'
        f'<input type="hidden" name="q" value="{_esc(query)}">'
        f'<input type="hidden" name="band" value="{_esc(band)}">'
        f'<input type="hidden" name="date" value="{_esc(date_end)}">'
        f'<input type="hidden" name="days" value="{days}">'
    )


def _render_json_section(title: str, value) -> str:
    return (
        f"<article><h3>{_esc(title)}</h3>{_render_structured(value)}</article>"
    )


def _render_readable_evidence(view: dict) -> str:
    """Render candidate evidence as adaptive, source-grounded prose."""
    sections = []
    for section in _candidate_evidence_sections(view):
        heading = str(section["heading"])
        items = section["items"]
        if heading == "Requirements":
            body = _render_evidence_list(items, include_metadata=True)
        elif heading == "Decision notes":
            body = _render_decision_notes(items)
        else:
            body = "".join(
                f'<p><span class="evidence-label">{_esc(item["label"])}:</span> '
                f'{_esc(item["value"])}</p>'
                for item in items
            )
        sections.append(
            '<section class="evidence-section">'
            f"<h3>{_esc(heading)}</h3>{body}</section>"
        )

    notice = view.get("notice") if isinstance(view.get("notice"), dict) else {}
    original_text = _first_text(
        notice.get("raw_text"),
        notice.get("description"),
    )
    original = ""
    if original_text:
        original = (
            '<details class="original-listing">'
            "<summary>Original listing text</summary>"
            f'<div class="original-listing-text">{_esc(original_text)}</div>'
            "</details>"
        )
    return f'<div class="readable-evidence">{"".join(sections)}{original}</div>'


def _render_evidence_list(
    items: list[dict[str, str]],
    *,
    include_metadata: bool = False,
) -> str:
    rendered = []
    for item in items:
        label = _clean_text(item.get("description") or item.get("label"))
        value = _clean_text(item.get("value"))
        primary = label or value
        metadata = []
        if include_metadata:
            importance = _clean_text(item.get("importance"))
            evidence = _clean_text(item.get("evidence"))
            if importance:
                metadata.append(_humanize(importance))
            if evidence:
                metadata.append(evidence)
        elif label and value:
            metadata.append(value)
        detail = (
            f'<span class="evidence-metadata">{_esc(" · ".join(metadata))}</span>'
            if metadata
            else ""
        )
        rendered.append(f"<li>{_esc(primary)}{detail}</li>")
    return f'<ul class="evidence-list">{"".join(rendered)}</ul>'


def _render_decision_notes(items: list[dict[str, object]]) -> str:
    rendered = []
    for item in items:
        label = _clean_text(item.get("label"))
        if label.casefold().startswith("requirement "):
            suffix = label.rsplit(" ", 1)[-1]
            if suffix.isdigit():
                label = ""
        details = item.get("details")
        detail_values = (
            [
                _clean_text(detail.get("value"))
                for detail in details
                if isinstance(detail, dict) and _clean_text(detail.get("value"))
            ]
            if isinstance(details, list)
            else []
        )
        prefix = (
            f'<span class="evidence-label">{_esc(label)}:</span> '
            if label
            else ""
        )
        rendered.append(f"<li>{prefix}{_esc(' · '.join(detail_values))}</li>")
    return f'<ul class="evidence-list">{"".join(rendered)}</ul>'


def _render_list_section(title: str, items: list[str]) -> str:
    body = (
        "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"
        if items
        else '<p class="muted">None recorded.</p>'
    )
    return f"<article><h3>{_esc(title)}</h3>{body}</article>"


def _render_structured(value) -> str:
    if isinstance(value, dict):
        if not value:
            return '<p class="muted">None recorded.</p>'
        return "<dl>" + "".join(
            f"<dt>{_esc(_humanize(key))}</dt><dd>{_render_structured(item)}</dd>"
            for key, item in value.items()
        ) + "</dl>"
    if isinstance(value, list):
        if not value:
            return '<p class="muted">None recorded.</p>'
        return "<ul>" + "".join(
            f"<li>{_render_structured(item)}</li>" for item in value
        ) + "</ul>"
    if value in (None, ""):
        return '<span class="muted">Not recorded</span>'
    return _esc(value)


def _candidate_identity(row) -> tuple[str, str, str]:
    return (
        str(_row_value(row, "candidate_type") or ""),
        str(_row_value(row, "project_key") or ""),
        str(_row_value(row, "role_key") or ""),
    )


def _scoring_snapshot(payload: dict) -> ScoringSnapshot:
    return ScoringSnapshot(
        version=str(payload.get("version", "")),
        component_maxima=_integer_dict(payload.get("component_maxima")),
        cap_values=_integer_dict(payload.get("cap_values")),
        band_thresholds=_integer_dict(payload.get("band_thresholds")),
    )


def _fallback_snapshot(subscores: dict[str, int]) -> ScoringSnapshot:
    return ScoringSnapshot(
        version="unavailable",
        component_maxima=dict(subscores),
        cap_values={},
        band_thresholds={
            "top_priority": 90,
            "strong_candidate": 75,
            "maybe_review": 60,
            "low_priority": 40,
        },
    )


def _correction_redirect(params: dict[str, list[str]], status: str) -> str:
    values = {
        "id": _param(params, "candidate_id"),
        "q": _param(params, "q"),
        "band": _param(params, "band", "all"),
        "date": _param(params, "date"),
        "days": _param(params, "days", "1"),
        "correction": status,
    }
    return "/candidates?" + urlencode(values)


def _date_filter_context(params: dict[str, list[str]]) -> tuple[str, int]:
    raw_date = _param(params, "date")
    try:
        if (
            len(raw_date) != 10
            or raw_date[4] != "-"
            or raw_date[7] != "-"
            or not (raw_date[:4] + raw_date[5:7] + raw_date[8:]).isdigit()
        ):
            raise ValueError
        date_end = date.fromisoformat(raw_date).isoformat()
    except ValueError:
        date_end = date.today().isoformat()
    days = 7 if _param(params, "days") == "7" else 1
    return date_end, days


def _candidate_display_title(view: dict) -> str:
    notice = view.get("notice")
    if isinstance(notice, dict):
        project = notice.get("project")
        role = notice.get("role")
        if isinstance(project, str) and isinstance(role, str):
            project = project.strip()
            role = role.strip()
            if project and role:
                return f"{project} — {role}"
    return str(view.get("title") or "Untitled Candidate")


def _flatten_requirements(value: object) -> list[dict[str, str]]:
    """Return useful requirement facts without extraction wrapper keys."""
    flattened: list[dict[str, str]] = []
    seen = set()

    def visit(item: object, semantic_key: str = "") -> None:
        if isinstance(item, str):
            description = item.strip()
            if description:
                if semantic_key and not _is_numbered_requirement_key(
                    semantic_key
                ):
                    append(_humanize(semantic_key), "", description)
                else:
                    append(description, "", "")
            return
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return

        description = _clean_text(item.get("description"))
        importance = _clean_text(item.get("importance"))
        evidence = _clean_text(item.get("evidence"))
        if (
            not description
            and semantic_key
            and not _is_numbered_requirement_key(semantic_key)
            and (importance or evidence)
        ):
            description = _humanize(semantic_key)
        if description or importance or evidence:
            if description and evidence and description.casefold() == evidence.casefold():
                evidence = ""
            append(description, importance, evidence)
            return
        for key, child in item.items():
            visit(child, str(key))

    def append(description: str, importance: str, evidence: str) -> None:
        evidence_key = evidence.casefold()
        if (
            not description
            and evidence_key
            and any(existing[2] == evidence_key for existing in seen)
        ):
            return
        signature = (
            description.casefold(),
            importance.casefold(),
            evidence_key,
        )
        if signature in seen:
            return
        seen.add(signature)
        flattened.append(
            {
                "description": description,
                "importance": importance,
                "evidence": evidence,
            }
        )

    visit(value)
    return flattened


def _candidate_evidence_sections(view: dict) -> list[dict[str, object]]:
    """Build adaptive, source-grounded evidence sections for a candidate."""
    notice = view.get("notice") if isinstance(view.get("notice"), dict) else {}
    features = (
        view.get("features") if isinstance(view.get("features"), dict) else {}
    )
    sections: list[dict[str, object]] = []
    is_role_candidate = bool(_clean_text(notice.get("role"))) or (
        _clean_text(view.get("candidate_type")) == "role"
    )

    def add_section(heading: str, items: list[dict[str, object]]) -> None:
        useful = [
            item
            for item in items
            if any(
                _clean_text(value)
                or (isinstance(value, (list, dict)) and bool(value))
                for value in item.values()
            )
        ]
        if useful:
            sections.append({"heading": heading, "items": useful})

    role_description = _first_text(
        notice.get("description") if is_role_candidate else "",
    )
    if is_role_candidate:
        add_section(
            "Role",
            _labeled_items(
                ("Description", role_description),
                (
                    "Type",
                    _humanize(features["role_type"])
                    if _clean_text(features.get("role_type"))
                    else "",
                ),
            ),
        )

    project_description = _first_text(
        notice.get("description") if not is_role_candidate else "",
    )
    add_section(
        "Project",
        _labeled_items(
            ("Description", project_description),
            (
                "Type",
                _humanize(features["project_type"])
                if _clean_text(features.get("project_type"))
                else "",
            ),
        ),
    )

    add_section(
        "Where and when",
        _labeled_items(
            ("Location", notice.get("location")),
            ("Shooting locations", notice.get("shooting_locations")),
            ("Shooting dates", notice.get("shooting_dates")),
        ),
    )

    compensation_items: list[dict[str, str]] = []
    feature_compensation = features.get("compensation")
    if isinstance(feature_compensation, dict):
        compensation_items.extend(
            _labeled_items(
                *(
                    (_humanize(key), value)
                    for key, value in feature_compensation.items()
                )
            )
        )
    elif feature_compensation:
        compensation_items.extend(
            _labeled_items(("Compensation", feature_compensation))
        )
    compensation_items.extend(
        _labeled_items(
            ("Listing terms", notice.get("compensation")),
        )
    )
    add_section("Compensation", _deduplicate_items(compensation_items))

    requirements = _flatten_requirements(features.get("requirements"))
    if requirements:
        sections.append({"heading": "Requirements", "items": requirements})

    decision_items = _decision_note_items(view.get("requirement_matches"))
    add_section("Decision notes", decision_items)
    return sections


def _decision_note_items(value: object) -> list[dict[str, object]]:
    records: list[tuple[str, dict]] = []
    if isinstance(value, list):
        records.extend(("", item) for item in value if isinstance(item, dict))
    elif isinstance(value, dict):
        if any(
            key in value
            for key in ("status", "local_value", "evidence", "reason")
        ):
            records.append(("", value))
        else:
            records.extend(
                (str(key), item)
                for key, item in value.items()
                if isinstance(item, dict)
            )

    items = []
    for wrapper_key, record in records:
        source_key = _clean_text(
            record.get("description")
            or record.get("requirement")
            or record.get("requirement_key")
        )
        if not source_key and not wrapper_key.lower().startswith("requirement_"):
            source_key = wrapper_key
        label = _humanize(source_key) if source_key else "Requirement"
        details = _labeled_items(
            ("Status", _humanize(record.get("status")) if record.get("status") else ""),
            ("Local value", record.get("local_value")),
            ("Evidence", record.get("evidence")),
            ("Reason", record.get("reason")),
        )
        if details:
            items.append({"label": label, "details": details})
    return items


def _labeled_items(*pairs) -> list[dict[str, str]]:
    return [
        {"label": str(label), "value": text}
        for label, value in pairs
        if (text := _clean_text(value))
    ]


def _deduplicate_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    for item in items:
        value_key = _normalize_containment_text(item["value"])
        existing_keys = [
            _normalize_containment_text(existing["value"]) for existing in result
        ]
        if any(value_key in existing_key for existing_key in existing_keys):
            continue
        contained_indexes = [
            index
            for index, existing_key in enumerate(existing_keys)
            if existing_key in value_key
        ]
        if contained_indexes:
            insert_at = contained_indexes[0]
            result = [
                existing
                for index, existing in enumerate(result)
                if index not in contained_indexes
            ]
            result.insert(insert_at, item)
        else:
            result.append(item)
    return result


def _normalize_containment_text(value: str) -> str:
    return " ".join(value.replace("_", " ").casefold().split())


def _first_text(*values: object) -> str:
    for value in values:
        if text := _clean_text(value):
            return text
    return ""


def _clean_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _is_numbered_requirement_key(value: str) -> bool:
    prefix, separator, suffix = value.casefold().rpartition("_")
    return bool(separator and prefix == "requirement" and suffix.isdigit())


def _date_navigation(query: str, band: str, date_end: str, days: int) -> str:
    selected_date = date.fromisoformat(date_end)

    def href(target_date: date, target_days: int = days) -> str:
        return "/candidates?" + urlencode(
            {
                "q": query,
                "band": band,
                "date": target_date.isoformat(),
                "days": target_days,
            }
        )

    previous = href(selected_date - timedelta(days=1))
    today = href(date.today())
    following = href(selected_date + timedelta(days=1))
    toggle_days = 1 if days == 7 else 7
    seven_days = href(selected_date, toggle_days)
    seven_days_pressed = "true" if days == 7 else "false"
    return (
        f'<a class="date-nav" href="{_esc(previous)}" '
        'aria-label="Previous day">&lt;</a>'
        f'<a class="date-nav" href="{_esc(today)}">Today</a>'
        f'<a class="date-nav" href="{_esc(following)}" '
        'aria-label="Next day">&gt;</a>'
        f'<a class="date-nav" href="{_esc(seven_days)}" '
        f'aria-pressed="{seven_days_pressed}">7 days</a>'
    )


def _band_options(selected: str) -> str:
    bands = (
        ("all", "All"),
        ("top_priority", "Top Priority"),
        ("strong_candidate", "Strong Candidate"),
        ("maybe_review", "Maybe Review"),
        ("low_priority", "Low Priority"),
        ("not_worth_applying_today", "Not Worth Applying Today"),
    )
    return "".join(
        f'<option value="{value}"{" selected" if value == selected else ""}>{label}</option>'
        for value, label in bands
    )


def _required_int(params: dict[str, list[str]], key: str) -> int:
    try:
        return int(_param(params, key))
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _optional_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _param(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    return values[-1] if values else default


def _row_value(row, key: str):
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _json_dict(value: object) -> dict:
    parsed = _json_value(value, {})
    return parsed if isinstance(parsed, dict) else {}


def _json_value(value: object, default):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (json.JSONDecodeError, TypeError):
        return default


def _integer_dict(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, item in value.items():
        try:
            result[str(key)] = int(item)
        except (TypeError, ValueError):
            continue
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _humanize(value: object) -> str:
    return str(value or "unknown").replace("_", " ").strip().title()


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


_CSS = """
:root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #f4f1ea; color: #20251f; }
header { padding: 12px 22px; background: #20342b; color: white; }
header h1, header p { margin: 0; }
header p { margin-top: 5px; color: #d8e2dc; }
main { padding: 10px 22px 20px; }
.filters { display: flex; gap: 9px; align-items: end; margin-bottom: 9px; }
label { display: grid; gap: 5px; font-size: 12px; font-weight: 700; }
input, select, button { border: 1px solid #b9b3a7; border-radius: 7px; padding: 8px 10px; font: inherit; }
button, .date-nav { background: #284d3d; color: white; cursor: pointer; }
button.secondary { background: white; color: #31443b; }
.date-nav { border: 1px solid #b9b3a7; border-radius: 7px; padding: 8px 10px; font: inherit; text-decoration: none; }
.score-workbench { --candidate-list-width: 22%; height: calc(100vh - 132px); min-height: 570px; display: grid; grid-template-columns: minmax(220px, var(--candidate-list-width)) 6px minmax(480px, 1fr); overflow: hidden; background: white; border: 1px solid #d8d2c7; }
.candidate-list { overflow-y: auto; border-right: 1px solid #ddd7cc; background: #faf8f3; }
.workbench-divider { cursor: col-resize; touch-action: none; }
.workbench-divider.active { background: #8fa99d; }
.candidate-list-item { display: flex; gap: 12px; padding: 14px; color: inherit; text-decoration: none; border-bottom: 1px solid #e5dfd5; border-left: 4px solid transparent; }
.candidate-list-item.selected { background: white; border-left-color: #315a48; }
.list-score { width: 46px; height: 46px; display: grid; place-items: center; border-radius: 12px; font-size: 20px; font-weight: 800; background: #ebe7dd; }
.list-copy { min-width: 0; display: grid; gap: 5px; }
.list-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.list-copy small, .muted, .agent-metadata { color: #716d64; }
.candidate-detail { min-width: 0; display: flex; flex-direction: column; overflow: hidden; }
.detail-heading { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding: 14px 18px 10px; }
.detail-heading h2 { margin: 0; }
.detail-score { font-size: 30px; line-height: 1; color: #20342b; }
.evidence-pane { flex: 1 1 auto; min-height: 0; overflow-y: auto; padding: 0 18px 12px; }
.readable-evidence { max-width: 760px; overflow-wrap: anywhere; }
.evidence-section { padding: 16px 0; border-bottom: 1px solid #e6e1d8; }
.evidence-section h3 { margin: 0 0 9px; font-size: 12px; font-weight: 650; text-transform: uppercase; letter-spacing: .04em; color: #5d665f; }
.evidence-section p, .evidence-section li { font-weight: 400; line-height: 1.6; }
.evidence-section p { margin: 5px 0; }
.evidence-label { font-weight: 600; color: #3d4942; }
.evidence-list { margin: 0; }
.evidence-metadata { display: block; color: #716d64; font-size: 12px; }
.original-listing { padding: 16px 0; color: #4d5750; }
.original-listing summary { cursor: pointer; font-size: 12px; font-weight: 600; }
.original-listing-text { margin-top: 10px; white-space: pre-wrap; font-weight: 400; line-height: 1.6; }
dl { margin: 0; }
dt { font-weight: 750; margin-top: 7px; }
dd { margin: 3px 0 0 10px; }
ul { margin: 6px 0; padding-left: 20px; }
.score-pane { flex: 0 0 auto; max-height: 260px; border-top: 1px solid #8d948f; background: white; }
.correction-grid-wrapper { overflow-x: auto; }
.correction-grid { width: 100%; min-width: 620px; border-collapse: collapse; table-layout: fixed; font-size: 12px; }
.correction-grid th, .correction-grid td { border: 1px solid #aeb4b0; padding: 5px; vertical-align: top; }
.correction-grid thead th { background: #dfe8e2; color: #20342b; text-align: left; }
.correction-grid th:first-child { width: 110px; background: #edf2ee; }
.correction-form { display: grid; grid-template-columns: minmax(54px, .55fr) minmax(90px, 1fr); gap: 4px; }
.correction-form input { min-width: 0; width: 100%; border-radius: 0; padding: 4px 5px; font-size: 11px; }
.actions { grid-column: 1 / -1; display: flex; gap: 4px; }
.actions button { border-radius: 0; padding: 4px 6px; font-size: 10px; }
.empty { padding: 25px; background: white; border-radius: 12px; }
.band-top_priority .list-score, .overall.band-top_priority { color: #0d6a42; }
.band-strong_candidate .list-score, .overall.band-strong_candidate { color: #34724f; }
.band-maybe_review .list-score, .overall.band-maybe_review { color: #9a6b12; }
.band-low_priority .list-score, .overall.band-low_priority { color: #ae572d; }
.band-not_worth_applying_today .list-score, .overall.band-not_worth_applying_today { color: #983c3c; }
@media (max-width: 800px) {
  header, main { padding-left: 14px; padding-right: 14px; }
  .filters { align-items: stretch; flex-direction: column; }
  .score-workbench { height: auto; grid-template-columns: 1fr; overflow: visible; }
  .workbench-divider { display: none; }
  .candidate-list { max-height: 280px; border-right: 0; border-bottom: 1px solid #ddd7cc; }
  .candidate-detail { display: block; overflow: visible; }
  .evidence-pane, .score-pane { max-height: none; overflow: auto; }
}
"""


_JS = """
document.querySelectorAll('.score-workbench').forEach((workbench) => {
  const divider = workbench.querySelector('.workbench-divider');
  const candidateList = workbench.querySelector('.candidate-list');
  const minimumLeft = 220;
  const minimumRight = 480;
  let activePointer = null;
  let userAdjusted = false;
  let adjustedLeftWidth = null;

  const bounds = () => {
    const rect = workbench.getBoundingClientRect();
    const contentWidth = workbench.clientWidth;
    const maximumLeft = Math.max(
      minimumLeft,
      contentWidth - minimumRight - divider.offsetWidth
    );
    divider.setAttribute('aria-valuemax', String(Math.round(maximumLeft)));
    return {rect, maximumLeft};
  };
  const setLeftWidth = (width) => {
    const {maximumLeft} = bounds();
    const leftWidth = Math.round(
      Math.min(maximumLeft, Math.max(minimumLeft, width))
    );
    workbench.style.setProperty('--candidate-list-width', `${leftWidth}px`);
    divider.setAttribute('aria-valuenow', String(leftWidth));
    return leftWidth;
  };
  const synchronizeDivider = () => {
    const {maximumLeft} = bounds();
    if (window.matchMedia('(max-width: 800px)').matches) {
      const current = userAdjusted
        ? adjustedLeftWidth
        : candidateList.getBoundingClientRect().width;
      divider.setAttribute(
        'aria-valuenow',
        String(Math.round(Math.min(maximumLeft, Math.max(minimumLeft, current))))
      );
      return;
    }
    if (userAdjusted) {
      adjustedLeftWidth = setLeftWidth(adjustedLeftWidth);
      return;
    }
    workbench.style.removeProperty('--candidate-list-width');
    const defaultWidth = candidateList.getBoundingClientRect().width;
    divider.setAttribute(
      'aria-valuenow',
      String(Math.round(
        Math.min(maximumLeft, Math.max(minimumLeft, defaultWidth))
      ))
    );
  };
  const finishResize = (event) => {
    if (activePointer !== event.pointerId) return;
    divider.classList.remove('active');
    activePointer = null;
  };

  synchronizeDivider();
  const resizeObserver = new ResizeObserver(synchronizeDivider);
  resizeObserver.observe(workbench);
  divider.addEventListener('pointerdown', (event) => {
    activePointer = event.pointerId;
    divider.setPointerCapture(event.pointerId);
    divider.classList.add('active');
  });
  divider.addEventListener('pointermove', (event) => {
    if (activePointer !== event.pointerId) return;
    const {rect} = bounds();
    userAdjusted = true;
    adjustedLeftWidth = setLeftWidth(event.clientX - rect.left);
  });
  divider.addEventListener('pointerup', finishResize);
  divider.addEventListener('pointercancel', finishResize);
  divider.addEventListener('lostpointercapture', finishResize);
  divider.addEventListener('keydown', (event) => {
    const {maximumLeft} = bounds();
    const current = Number(divider.getAttribute('aria-valuenow'));
    let next;
    if (event.key === 'ArrowLeft') next = current - 16;
    else if (event.key === 'ArrowRight') next = current + 16;
    else if (event.key === "Home") next = minimumLeft;
    else if (event.key === "End") next = maximumLeft;
    else return;
    event.preventDefault();
    userAdjusted = true;
    adjustedLeftWidth = setLeftWidth(next);
  });
});

document.querySelectorAll('.score-pane').forEach((pane) => {
  const agent = JSON.parse(pane.dataset.agentSubscores || '{}');
  const active = JSON.parse(pane.dataset.activeCorrections || '{}');
  const caps = JSON.parse(pane.dataset.capValues || '[]');
  pane.querySelectorAll('.correction-input').forEach((input) => {
    input.addEventListener('input', () => {
      const feedback = input.form.querySelector('.feedback-input');
      if (input.value !== '') {
        feedback.disabled = false;
      } else {
        feedback.disabled = true;
      }
      const merged = {...agent, ...active};
      const component = input.closest('td').dataset.component;
      if (input.value !== '') merged[component] = Number(input.value);
      const preCapTotal = Object.values(merged)
        .reduce((sum, value) => sum + Number(value), 0);
      let overall = preCapTotal;
      if (caps.length) overall = Math.min(overall, ...caps);
      overall = Math.max(0, Math.min(100, Math.round(overall)));
      document.querySelector('[data-pre-cap-total]').textContent = preCapTotal;
      document.querySelector('[data-overall]').textContent = overall;
    });
  });
  pane.querySelectorAll('.correction-input, .feedback-input').forEach((input) => {
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        event.currentTarget.form.requestSubmit();
      }
    });
  });
});
"""
