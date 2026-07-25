from __future__ import annotations

import html
import json
from dataclasses import asdict
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
    rows = store.search_candidate_workbench_rows(
        query=query,
        band=band,
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
        _render_workbench(views, selected, query, band)
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
      <h1>Score Review Workbench</h1>
      <p>Compare extraction, agent scores, and current component corrections.</p>
    </div>
  </header>
  <main>
    {notice}
    <form class="filters" method="get" action="/candidates">
      <label>Search<input name="q" value="{_esc(query)}" placeholder="Candidate title"></label>
      <label>Agent score band<select name="band">{_band_options(band)}</select></label>
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


def _render_workbench(views: list[dict], selected: dict, query: str, band: str) -> str:
    candidates = "".join(
        _render_candidate_list_item(view, selected["id"], query, band)
        for view in views
    )
    return f"""
    <section class="score-workbench">
      <nav class="candidate-list" aria-label="Candidates">{candidates}</nav>
      <section class="candidate-detail">
        {_render_candidate_detail(selected, query, band)}
      </section>
    </section>
    """


def _render_candidate_list_item(
    view: dict,
    selected_id: int,
    query: str,
    band: str,
) -> str:
    params = urlencode(
        {"id": view["id"], "q": query, "band": band},
    )
    selected_class = " selected" if view["id"] == selected_id else ""
    return f"""
    <a class="candidate-list-item band-{_esc(view["display_band"])}{selected_class}"
       href="/candidates?{_esc(params)}">
      <span class="list-score">{view["display_overall"]}</span>
      <span class="list-copy">
        <strong>{_esc(view["title"])}</strong>
        <small>{_esc(view["effective_project_date"] or "Date unknown")} · {_esc(_humanize(view["candidate_type"]))}</small>
      </span>
    </a>
    """


def _render_candidate_detail(view: dict, query: str, band: str) -> str:
    warnings = "".join(
        f'<p class="warning">{_esc(warning)}</p>' for warning in view["warnings"]
    )
    caps = (
        " ".join(
            f'<span class="cap">{_esc(cap["label"])} ≤ {cap["value"]}</span>'
            for cap in view["caps"]
        )
        or '<span class="muted">No active caps</span>'
    )
    corrected_note = (
        f'<span class="agent-original">Agent overall: {view["agent_overall"]}</span>'
        if view["display_overall"] != view["agent_overall"]
        else ""
    )
    return f"""
      <div class="detail-heading">
        <div><p class="eyebrow">{_esc(_humanize(view["candidate_type"]))}</p>
        <h2>{_esc(view["title"])}</h2></div>
        <div class="overall band-{_esc(view["display_band"])}">
          <span>Overall</span><strong data-overall>{view["display_overall"]}</strong>
          <small data-band>{_esc(_humanize(view["display_band"]))}</small>
          {corrected_note}
        </div>
      </div>
      <section class="evidence-pane">
        {warnings}
        <div class="evidence-grid">
          {_render_json_section("Listing", view["notice"])}
          {_render_json_section("Extracted features", view["features"])}
          {_render_json_section("Requirement matches", view["requirement_matches"])}
          {_render_list_section("Positive drivers", view["positive_drivers"])}
          {_render_list_section("Negative drivers", view["negative_drivers"])}
          {_render_json_section("Score trace", view["score_trace"])}
        </div>
      </section>
      <section class="score-pane"
        data-agent-subscores="{_esc(json.dumps({name: item["agent_score"] for name, item in view["components"].items()}))}"
        data-active-corrections="{_esc(json.dumps({name: item["corrected_score"] for name, item in view["components"].items() if item["active"]}))}"
        data-cap-values="{_esc(json.dumps([cap["value"] for cap in view["caps"]]))}"
        data-band-thresholds="{_esc(json.dumps(view["snapshot"]["band_thresholds"]))}">
        <div class="caps-bar"><strong>Active caps</strong>{caps}</div>
        <div class="score-table">
          <div class="score-row score-header">
            <span>Component</span><span>Agent</span><span>Correction</span>
            <span>Reason (optional)</span><span>Action</span>
          </div>
          {"".join(_render_component_row(view, component, query, band) for component in view["components"].values())}
        </div>
        <p class="agent-metadata">Agent rank: {_esc(view["agent_rank"] or "Unranked")} · Agent draft suggestion: {"Yes" if view["agent_draft_suggestion"] else "No"}</p>
      </section>
    """


def _render_component_row(
    view: dict,
    component: dict,
    query: str,
    band: str,
) -> str:
    hidden = _hidden_context(view["id"], component["name"], query, band)
    correction_value = (
        str(component["corrected_score"])
        if component["corrected_score"] is not None
        else ""
    )
    status = ""
    action = "/candidate-correction"
    button = "Save"
    if component["stale"]:
        status = (
            f'<small class="stale">Stale: max changed from '
            f'{component["saved_max"]} to {component["maximum"]}</small>'
        )
        action = "/candidate-correction/reconfirm"
        button = "Reconfirm"
    elif component["version_warning"]:
        status = '<small class="warning-inline">Saved under an earlier scoring version</small>'
    disabled = " disabled" if not view["correction_enabled"] else ""
    reset = (
        '<button class="secondary" type="submit" '
        'formaction="/candidate-correction/reset">Reset</button>'
        if component["corrected_score"] is not None
        else ""
    )
    return f"""
      <div class="score-row" data-component="{_esc(component["name"])}">
        <span><strong>{_esc(component["label"])}</strong><small>Max {component["maximum"]}</small>{status}</span>
        <span class="agent-cell">{component["agent_score"]}</span>
        <form class="correction-form" method="post" action="{action}">
          {hidden}
          <input class="correction-input" name="corrected_score" type="number"
            min="0" max="{component["maximum"]}" value="{_esc(correction_value)}"{disabled}>
          <input name="reason" value="{_esc(component["reason"])}"
            placeholder="Optional note"{disabled}>
          <span class="actions"><button type="submit"{disabled}>{button}</button>{reset}</span>
        </form>
      </div>
    """


def _hidden_context(
    candidate_id: int,
    component_name: str,
    query: str,
    band: str,
) -> str:
    return (
        f'<input type="hidden" name="candidate_id" value="{candidate_id}">'
        f'<input type="hidden" name="component_name" value="{_esc(component_name)}">'
        f'<input type="hidden" name="q" value="{_esc(query)}">'
        f'<input type="hidden" name="band" value="{_esc(band)}">'
    )


def _render_json_section(title: str, value) -> str:
    return (
        f"<article><h3>{_esc(title)}</h3>{_render_structured(value)}</article>"
    )


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
        "correction": status,
    }
    return "/candidates?" + urlencode(values)


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
header { padding: 20px 28px; background: #20342b; color: white; }
header h1, header p { margin: 0; }
header p { margin-top: 5px; color: #d8e2dc; }
main { padding: 18px 28px 28px; }
.filters { display: flex; gap: 12px; align-items: end; margin-bottom: 14px; }
label { display: grid; gap: 5px; font-size: 12px; font-weight: 700; }
input, select, button { border: 1px solid #b9b3a7; border-radius: 7px; padding: 8px 10px; font: inherit; }
button { background: #284d3d; color: white; cursor: pointer; }
button.secondary { background: white; color: #31443b; }
.score-workbench { height: calc(100vh - 170px); min-height: 570px; display: grid; grid-template-columns: minmax(250px, 32%) minmax(0, 68%); overflow: hidden; background: white; border: 1px solid #d8d2c7; border-radius: 14px; }
.candidate-list { overflow-y: auto; border-right: 1px solid #ddd7cc; background: #faf8f3; }
.candidate-list-item { display: flex; gap: 12px; padding: 14px; color: inherit; text-decoration: none; border-bottom: 1px solid #e5dfd5; border-left: 4px solid transparent; }
.candidate-list-item.selected { background: white; border-left-color: #315a48; }
.list-score { width: 46px; height: 46px; display: grid; place-items: center; border-radius: 12px; font-size: 20px; font-weight: 800; background: #ebe7dd; }
.list-copy { min-width: 0; display: grid; gap: 5px; }
.list-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.list-copy small, .muted, .agent-metadata { color: #716d64; }
.candidate-detail { min-width: 0; display: grid; grid-template-rows: auto minmax(150px, 1fr) auto; overflow: hidden; }
.detail-heading { display: flex; justify-content: space-between; gap: 18px; padding: 18px 20px 12px; }
.detail-heading h2 { margin: 0; }
.eyebrow { margin: 0 0 4px; color: #6b746e; font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
.overall { min-width: 130px; display: grid; text-align: right; }
.overall strong { font-size: 34px; line-height: 1; }
.overall small { font-weight: 700; }
.agent-original { font-size: 11px; color: #716d64; }
.evidence-pane { overflow-y: auto; padding: 0 20px 18px; }
.evidence-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.evidence-grid article { padding: 13px; background: #f8f6f1; border-radius: 10px; overflow-wrap: anywhere; }
.evidence-grid h3 { margin: 0 0 9px; font-size: 13px; }
dl { margin: 0; }
dt { font-weight: 750; margin-top: 7px; }
dd { margin: 3px 0 0 10px; }
ul { margin: 6px 0; padding-left: 20px; }
.score-pane { max-height: 320px; overflow: auto; border-top: 1px solid #d8d2c7; background: white; }
.caps-bar { position: sticky; top: 0; z-index: 3; display: flex; gap: 8px; align-items: center; padding: 9px 14px; background: #f0ede5; }
.cap { padding: 4px 7px; border-radius: 999px; background: #f2d9a7; font-size: 11px; }
.score-table { min-width: 760px; }
.score-row { display: grid; grid-template-columns: minmax(170px, 1fr) 70px 110px minmax(190px, 1fr) 155px; align-items: center; gap: 9px; padding: 8px 14px; border-top: 1px solid #eee9df; }
.score-header { position: sticky; top: 43px; z-index: 2; background: white; font-size: 11px; font-weight: 800; color: #6c6a63; }
.score-row > span:first-child { display: grid; }
.score-row small { font-size: 10px; color: #777168; }
.correction-form { display: contents; }
.correction-input { width: 100%; }
.actions { display: flex; gap: 6px; }
.actions form { display: inline; }
.stale { color: #a14f35 !important; }
.warning { margin: 0 0 10px; padding: 9px 12px; background: #fff1cf; border-radius: 8px; }
.notice { margin: 0 0 10px; padding: 9px 12px; background: #fff1cf; border-radius: 8px; }
.warning-inline { color: #8a6222 !important; }
.agent-metadata { margin: 8px 14px 12px; font-size: 11px; }
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
  .candidate-list { max-height: 280px; border-right: 0; border-bottom: 1px solid #ddd7cc; }
  .candidate-detail { display: block; overflow: visible; }
  .evidence-pane, .score-pane { max-height: none; overflow: auto; }
  .evidence-grid { grid-template-columns: 1fr; }
}
"""


_JS = """
document.querySelectorAll('.score-pane').forEach((pane) => {
  const agent = JSON.parse(pane.dataset.agentSubscores || '{}');
  const active = JSON.parse(pane.dataset.activeCorrections || '{}');
  const caps = JSON.parse(pane.dataset.capValues || '[]');
  const thresholds = JSON.parse(pane.dataset.bandThresholds || '{}');
  pane.querySelectorAll('.correction-input').forEach((input) => {
    input.addEventListener('input', () => {
      const merged = {...agent, ...active};
      const component = input.closest('.score-row').dataset.component;
      if (input.value !== '') merged[component] = Number(input.value);
      let overall = Object.values(merged).reduce((sum, value) => sum + Number(value), 0);
      if (caps.length) overall = Math.min(overall, ...caps);
      overall = Math.max(0, Math.min(100, Math.round(overall)));
      let band = 'not_worth_applying_today';
      if (overall >= thresholds.top_priority) band = 'top_priority';
      else if (overall >= thresholds.strong_candidate) band = 'strong_candidate';
      else if (overall >= thresholds.maybe_review) band = 'maybe_review';
      else if (overall >= thresholds.low_priority) band = 'low_priority';
      document.querySelector('[data-overall]').textContent = overall;
      document.querySelector('[data-band]').textContent = band.replaceAll('_', ' ');
    });
  });
});
"""
