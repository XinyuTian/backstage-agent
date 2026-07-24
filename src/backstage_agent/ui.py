from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .candidate_models import HumanFeedback
from .settings import load_settings
from .storage import DecisionStore


def _get_route(path: str) -> tuple[str, str | None]:
    if path == "/":
        return "redirect", "/candidates"
    if path == "/candidates":
        return "candidates", None
    return "not_found", None


def _post_route(path: str) -> str | None:
    return "candidate_feedback" if path == "/candidate-feedback" else None


class DashboardServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        settings = load_settings()
        self.store = DecisionStore(settings.database_path)

    def serve_forever(self) -> None:
        store = self.store

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
                    self._send_html(_render_candidates_index(store, parse_qs(parsed.query)))
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                if _post_route(urlparse(self.path).path) != "candidate_feedback":
                    self.send_error(404)
                    return
                length = int(self.headers.get("Content-Length", "0") or "0")
                params = parse_qs(self.rfile.read(length).decode("utf-8"))
                try:
                    _record_candidate_feedback_from_params(store, params)
                except ValueError as exc:
                    self.send_error(400, str(exc))
                    return
                self.send_response(303)
                self.send_header("Location", "/candidates?feedback=recorded")
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
) -> str:
    query = _param(params, "q")
    band = _param(params, "band", "all")
    rows = store.search_candidates(query=query, band=band, limit=200)
    feedback_message = (
        '<p class="notice">Feedback recorded.</p>'
        if _param(params, "feedback") == "recorded"
        else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Backstage Candidates</title>
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>Backstage Candidates</h1>
      <p>Ranked mutual-selection scores and calibration feedback</p>
    </div>
  </header>
  <main>
    {feedback_message}
    <form class="filters candidate-filters" method="get" action="/candidates">
      <label>Search<input name="q" value="{_esc(query)}" placeholder="Candidate title"></label>
      <label>Score band
        <select name="band">
          {_band_options(band)}
        </select>
      </label>
      <button type="submit">Filter</button>
    </form>
    <section class="candidate-grid">
      {_render_candidate_cards(rows)}
    </section>
  </main>
</body>
</html>"""


def _render_candidate_cards(rows) -> str:
    if not rows:
        return '<div class="empty">No candidates match the current filters.</div>'
    return "\n".join(_render_candidate_card(row) for row in rows)


def _render_candidate_card(row) -> str:
    score_payload = _json_dict(_row_value(row, "score_json"))
    positives = _json_list(score_payload.get("positive_drivers"))
    negatives = _json_list(score_payload.get("negative_drivers"))
    subscores = score_payload.get("subscores")
    if not isinstance(subscores, dict):
        subscores = {}
    rank_position = _row_value(row, "rank_position")
    rank_label = f"Rank #{rank_position}" if rank_position else "Unranked"
    return f"""
    <article class="candidate-card">
      <div class="candidate-card-header">
        <div>
          <span class="pill">{_esc(_humanize_score_band(_row_value(row, "score_band")))}</span>
          {_draft_chip(row)}
        </div>
        <span class="score">{int(_row_value(row, "overall_score") or 0)}</span>
      </div>
      <p class="meta">{_esc(rank_label)}</p>
      <h2>{_esc(_row_value(row, "title") or "Untitled Candidate")}</h2>
      {_candidate_subscores(subscores)}
      <h3>Positive Drivers</h3>
      {_list(positives) if positives else '<p class="muted">None recorded.</p>'}
      <h3>Negative Drivers</h3>
      {_list(negatives) if negatives else '<p class="muted">None recorded.</p>'}
      <form class="feedback-form" method="post" action="/candidate-feedback">
        <input type="hidden" name="candidate_id" value="{_esc(_row_value(row, "id"))}">
        <label>Human score<input name="human_score" type="number" min="0" max="100" placeholder="45"></label>
        <label>Affected component<input name="affected_components" placeholder="identity_match"></label>
        <label>Failure mode<input name="failure_modes" placeholder="overweighted_signal"></label>
        <label>Reason<input name="reason" placeholder="Explain the scoring error"></label>
        <button type="submit">Record Feedback</button>
      </form>
    </article>
    """


def _candidate_subscores(subscores: dict) -> str:
    if not subscores:
        return ""
    items = "".join(
        f"<li><span>{_esc(_humanize_score_band(key))}</span><strong>{_esc(value)}</strong></li>"
        for key, value in sorted(subscores.items())
    )
    return f'<ul class="subscores">{items}</ul>'


def _draft_chip(row) -> str:
    if _row_value(row, "draft_suggestion"):
        return '<span class="pill hold">Draft suggested</span>'
    return '<span class="pill muted-pill">No draft suggestion</span>'


def _humanize_score_band(value: object) -> str:
    return str(value or "unknown").replace("_", " ").strip().title()


def _record_candidate_feedback_from_params(
    store: DecisionStore,
    params: dict[str, list[str]],
) -> int:
    try:
        candidate_id = int(_param(params, "candidate_id"))
        human_score = int(_param(params, "human_score"))
    except ValueError as exc:
        raise ValueError("candidate_id and human_score must be numeric") from exc
    if not 0 <= human_score <= 100:
        raise ValueError("human_score must be between 0 and 100")
    candidate_row = _candidate_row_by_id(store, candidate_id)
    feedback = HumanFeedback(
        candidate_id=candidate_id,
        agent_score=int(candidate_row["overall_score"]),
        human_score=human_score,
        affected_components=_required_csv(
            "affected_components",
            _param(params, "affected_components"),
        ),
        failure_modes=_required_csv("failure_modes", _param(params, "failure_modes")),
        free_text_reason=_param(params, "reason").strip(),
    )
    if not feedback.free_text_reason:
        raise ValueError("reason must be non-empty")
    return store.record_candidate_feedback(feedback)


def _candidate_row_by_id(store: DecisionStore, candidate_id: int):
    for row in store.search_candidates(limit=1000000):
        if row["id"] == candidate_id:
            return row
    raise ValueError(f"Candidate {candidate_id} was not found.")


def _required_csv(field_name: str, value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if items:
        return items
    raise ValueError(f"{field_name} must include at least one non-empty value.")


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


def _param(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    return values[-1] if values else default


def _row_value(row, key: str):
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _json_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


_CSS = """
:root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; background: #f5f1e8; color: #24231f; }
header { display: flex; justify-content: space-between; padding: 24px 32px; background: #25332d; color: white; }
header h1, header p { margin: 0; }
header p { margin-top: 6px; color: #dce3df; }
main { padding: 24px 32px 48px; }
.filters { display: flex; gap: 16px; align-items: end; margin-bottom: 20px; }
label { display: grid; gap: 6px; font-size: 13px; font-weight: 650; }
input, select, button { border: 1px solid #b7b1a6; border-radius: 8px; padding: 10px 12px; font: inherit; }
button { background: #25332d; color: white; cursor: pointer; }
.candidate-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(330px, 1fr)); gap: 18px; }
.candidate-card { background: white; border: 1px solid #ded8cc; border-radius: 14px; padding: 20px; }
.candidate-card-header { display: flex; justify-content: space-between; gap: 12px; }
.candidate-card h2 { margin: 10px 0; }
.candidate-card h3 { margin-bottom: 6px; font-size: 14px; }
.pill { display: inline-block; border-radius: 999px; background: #e3eee8; padding: 5px 9px; font-size: 12px; }
.hold { background: #f2dfae; }
.muted-pill { background: #ece9e1; }
.score { font-size: 28px; font-weight: 750; }
.meta, .muted { color: #716d64; }
.subscores { padding: 0; list-style: none; }
.subscores li { display: flex; justify-content: space-between; border-bottom: 1px solid #eee9df; padding: 5px 0; }
.feedback-form { display: grid; gap: 10px; margin-top: 16px; }
.empty, .notice { background: white; border: 1px solid #ded8cc; border-radius: 12px; padding: 18px; }
@media (max-width: 720px) {
  header, main { padding-left: 16px; padding-right: 16px; }
  .filters { align-items: stretch; flex-direction: column; }
}
"""
