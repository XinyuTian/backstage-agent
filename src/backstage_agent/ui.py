from __future__ import annotations

import html
import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from .project_labels import extract_backstage_project_labels
from .settings import load_settings
from .storage import DecisionStore


class DashboardServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port
        self.settings = load_settings()
        self.store = DecisionStore(self.settings.database_path)

    def serve_forever(self) -> None:
        store = self.store
        settings = self.settings

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(_render_index(store, settings, parse_qs(parsed.query)))
                    return
                self.send_error(404)

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
        print(f"Decision UI running at http://{self.host}:{self.port}")
        server.serve_forever()


def _render_index(store: DecisionStore, settings, params: dict[str, list[str]]) -> str:
    query = _param(params, "q")
    decision = _normalize_decision(_param(params, "decision", "all"))
    method = _param(params, "method", "all")
    date_from = _date_param(params, "date_from", default=_default_date_from())
    date_to = _date_param(params, "date_to")
    selected = _param(params, "selected")
    rows = store.search_decisions(
        query=query,
        decision=decision,
        method=method,
        date_from=date_from,
        date_to=date_to,
        limit=200,
    )
    counts = store.decision_counts(
        query=query,
        method=method,
        decision="all",
        date_from=date_from,
        date_to=date_to,
    )
    screening_counts = store.screening_counts(
        query=query,
        decision=decision,
        date_from=date_from,
        date_to=date_to,
    )
    selected_row = next((row for row in rows if str(row["id"]) == selected), rows[0] if rows else None)
    selected_id = str(selected_row["id"]) if selected_row else ""
    history_href = _all_history_href(query=query, decision=decision, method=method)
    today_href = _today_href(query=query, decision=decision, method=method)
    seven_days_href = _seven_days_href(query=query, decision=decision, method=method)
    base_filters = {
        "q": query,
        "decision": decision,
        "method": method,
        "date_from": date_from,
        "date_to": date_to,
    }
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Backstage Decisions</title>
  <style>{_CSS}</style>
</head>
<body>
  <header>
    <div>
      <h1>Backstage Decisions</h1>
      <p>{_esc(settings.database_path)} · dry run {_bool_label(settings.dry_run)}</p>
    </div>
    <a class="button" href="/">Reset</a>
  </header>
  <main>
    <form class="filters" method="get">
      <label>Search<input name="q" value="{_esc(query)}" placeholder="Title, reason, notice text"></label>
      <div class="date-field">
        <span class="field-label">Project Date</span>
        <div class="date-picker" data-date-picker>
          <button class="date-picker-toggle" type="button" aria-haspopup="dialog" aria-expanded="false">
            <span data-range-label>{_esc(_date_range_label(date_from, date_to))}</span>
          </button>
          <input type="hidden" name="date_from" value="{_esc(date_from)}" data-date-from>
          <input type="hidden" name="date_to" value="{_esc(date_to)}" data-date-to>
          <div class="calendar-popover" data-calendar-popover hidden>
            <div class="calendar-head">
              <button type="button" class="calendar-nav" data-prev-month aria-label="Previous month">‹</button>
              <strong data-month-label></strong>
              <button type="button" class="calendar-nav" data-next-month aria-label="Next month">›</button>
            </div>
            <div class="calendar-weekdays" aria-hidden="true">
              <span>Sun</span><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span><span>Sat</span>
            </div>
            <div class="calendar-grid" data-calendar-grid></div>
          </div>
        </div>
      </div>
      <input type="hidden" name="decision" value="{_esc(decision)}">
      <input type="hidden" name="method" value="{_esc(method)}">
      <button type="submit">Search</button>
      <a class="shortcut-button" href="{_esc(today_href)}">Today</a>
      <a class="shortcut-button" href="{_esc(seven_days_href)}">7 days</a>
      <a class="shortcut-button" href="{_esc(history_href)}">All</a>
    </form>
    <section class="decision-toolbar" aria-label="Dashboard filters">
      <div class="toolbar-group status-group">
        <span class="toolbar-label">Status</span>
        <nav class="status-tabs" aria-label="Decision status">
          {_tab("All", counts["total"] or 0, "decision", "all", decision, base_filters)}
          {_tab("Approved", counts["passed_count"] or 0, "decision", "approved", decision, base_filters)}
          {_tab("Submitted", counts["applied_count"] or 0, "decision", "applied", decision, base_filters)}
          {_tab("Needs Check", counts["needs_check_count"] or 0, "decision", "needs_check", decision, base_filters)}
          {_tab("Rejected", counts["reject_count"] or 0, "decision", "reject", decision, base_filters)}
        </nav>
      </div>
      <div class="toolbar-group method-group">
        <span class="toolbar-label">Method</span>
        <nav class="method-tabs" aria-label="Screening method">
          {_method_tab("LLM", screening_counts["llm_count"] or 0, "llm", method, base_filters)}
          {_method_tab("Local", screening_counts["local_count"] or 0, "local", method, base_filters)}
        </nav>
      </div>
    </section>
    <div class="workspace">
      <section class="list" id="decision-list" aria-label="Decision list">
        {_render_rows(rows, params, selected_id)}
      </section>
      <section class="detail" aria-label="Decision detail">
        {_render_detail(selected_row)}
      </section>
    </div>
  </main>
  <script>{_JS}</script>
</body>
</html>"""


def _render_rows(rows, params: dict[str, list[str]], selected_id: str) -> str:
    if not rows:
        return '<div class="empty">No decisions match the current filters.</div>'
    return "\n".join(_render_row(row, params, selected_id) for row in rows)


def _render_row(row, params: dict[str, list[str]], selected_id: str) -> str:
    next_params = {key: values[-1] for key, values in params.items() if values}
    next_params["selected"] = str(row["id"])
    href = f"/?{urlencode(next_params)}"
    status, status_class = _decision_status(row)
    labels = _project_label_chips(_project_labels_from_row(row))
    selected_class = " selected" if str(row["id"]) == selected_id else ""
    return f"""
    <a class="row{selected_class}" href="{_esc(href)}" data-decision-row="{_esc(row["id"])}">
      <div class="row-top">
        <div class="row-labels">
          <span class="pill {status_class}">{status}</span>
          {labels}
        </div>
        <span class="score">{float(row["score"]):.2f}</span>
      </div>
      <strong>{_esc(row["title"])}</strong>
      <small>Project date {_esc(_project_date(row))} · scanned {_esc(row["created_at"])}</small>
    </a>
    """


def _render_detail(row) -> str:
    if row is None:
        return '<div class="empty">Select a decision to view details.</div>'
    notice = json.loads(row["notice_json"])
    reasons = json.loads(row["reasons_json"])
    concerns = json.loads(row["concerns_json"])
    status, status_class = _decision_status(row)
    url = row["application_url"]
    labels = _project_label_chips(_project_labels_from_notice(notice), "label-strip detail-labels")
    return f"""
      <div class="detail-header">
        <span class="pill {status_class}">{status}</span>
        <span class="score large">{float(row["score"]):.2f}</span>
      </div>
      <h2>{_esc(row["title"])}</h2>
      {labels}
      <div class="meta">Project date {_esc(_project_date(row))} · scanned {_esc(row["created_at"])} · {_screening_label(row)} · {_application_label(row)}</div>
      {_link(url)}
      {_application_problem_detail(row)}
      <h3>Reasons</h3>
      {_list(reasons)}
      <h3>Concerns</h3>
      {_list(concerns) if concerns else '<p class="muted">None recorded.</p>'}
      <h3>Reviewer</h3>
      {_reviewer_detail(row)}
      <h3>Parsed Notice</h3>
      <dl>
        {_field("Project", notice.get("project"))}
        {_field("Role", notice.get("role"))}
        {_field("Location", notice.get("location"))}
        {_field("Shooting Locations", row["shooting_locations"] or notice.get("shooting_locations"))}
        {_field("Shooting Dates", row["shooting_dates"] or notice.get("shooting_dates"))}
        {_field("Compensation", notice.get("compensation"))}
      </dl>
      <pre>{_esc(notice.get("description") or notice.get("raw_text") or "")}</pre>
    """


def _field(label: str, value: str | None) -> str:
    return f"<dt>{_esc(label)}</dt><dd>{_esc(value or 'Unknown')}</dd>"


def _link(url: str | None) -> str:
    if not url:
        return '<p class="muted">No application URL captured.</p>'
    return f'<a class="button primary" href="{_esc(url)}" target="_blank" rel="noreferrer">Open Application Link</a>'


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _reviewer_detail(row) -> str:
    status = row["reviewer_status"]
    if not row["should_apply"]:
        return '<p class="muted">Not reviewed because the first pass rejected it.</p>'
    if not status:
        return '<p class="muted">No reviewer result recorded yet.</p>'
    reasons = _json_list(row["reviewer_reasons_json"])
    concerns = _json_list(row["reviewer_concerns_json"])
    score = row["reviewer_score"]
    score_text = f" · score {float(score):.2f}" if score is not None else ""
    model_text = f" · {_esc(row['reviewer_model'])}" if row["reviewer_model"] else ""
    reasons_html = _list(reasons) if reasons else '<p class="muted">No reviewer reasons recorded.</p>'
    concerns_html = '<p class="muted">Reviewer concerns:</p>' + _list(concerns) if concerns else ""
    return (
        f'<p class="meta">Reviewer status: {_esc(status)}{score_text}{model_text}</p>'
        f"{reasons_html}"
        f"{concerns_html}"
    )


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    return [str(item) for item in data]


def _project_labels_from_row(row) -> list[str]:
    try:
        notice = json.loads(row["notice_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    return _project_labels_from_notice(notice)


def _project_labels_from_notice(notice: dict) -> list[str]:
    labels = notice.get("project_labels") or []
    if labels:
        return [str(label) for label in labels if str(label).strip()]
    return extract_backstage_project_labels(
        "\n".join(
            str(part)
            for part in [notice.get("raw_text"), notice.get("description")]
            if part
        )
    )


def _project_label_chips(labels: list[str], class_name: str = "label-strip") -> str:
    if not labels:
        return ""
    chips = "".join(f'<span class="project-label">{_esc(label)}</span>' for label in labels)
    return f'<div class="{_esc(class_name)}">{chips}</div>'


def _decision_status(row) -> tuple[str, str]:
    if row["should_apply"] and row["application_status"] == "submitted_backstage":
        return "Submitted", "applied"
    if row["should_apply"] and row["reviewer_status"] == "approved":
        return "Approved", "passed"
    if row["should_apply"]:
        return "Needs Check", "hold"
    return "Rejected", "reject"


def _screening_label(row) -> str:
    return "LLM screening" if row["llm_used"] else "Local rule screening"


def _application_label(row) -> str:
    status = row["application_status"]
    if status == "submitted_backstage":
        return "Submitted on Backstage"
    if status == "drafted":
        return "Reviewer approved; ready to submit"
    if status:
        return f"Application status: {status}"
    return "No application draft"


def _application_problem_detail(row) -> str:
    status = row["application_status"]
    if not status or status in {"drafted", "submitted_backstage"}:
        return ""
    reason = row["application_blocker_reason"] or _application_status_reason(status)
    return (
        "<h3>Application</h3>"
        f"<p><strong>Status:</strong> {_esc(_humanize_application_status(status))}</p>"
        f"<p class=\"muted\">{_esc(reason)}</p>"
    )


def _humanize_application_status(status: str) -> str:
    return status.replace("_", " ").strip().capitalize()


def _application_status_reason(status: str) -> str:
    if status == "blocked_no_live_adapter":
        return "The role was approved, but automatic Backstage submission is not available for this run."
    if status.startswith("blocked"):
        return "The role was approved, but the application could not be completed automatically."
    if status.startswith("failed"):
        return "The role was approved, but the application attempt failed."
    if status.startswith("needs"):
        return "The role was approved, but the application needs more information before submission."
    return "The role was approved, but the application did not reach submitted status."


def _project_date(row) -> str:
    return row["project_date"] or str(row["created_at"]).split()[0]


def _tab(
    label: str,
    count: int,
    key: str,
    value: str,
    current_value: str,
    filters: dict[str, str],
) -> str:
    next_filters = dict(filters)
    next_filters[key] = value
    next_filters.pop("selected", None)
    href = f"/?{urlencode(next_filters)}"
    active = " active" if value == current_value else ""
    return (
        f'<a class="tab{active}" href="{_esc(href)}">'
        f'<span>{_esc(label)}</span><strong>{count}</strong></a>'
    )


def _method_tab(
    label: str,
    count: int,
    value: str,
    current_value: str,
    filters: dict[str, str],
) -> str:
    next_filters = dict(filters)
    next_filters["method"] = "all" if value == current_value else value
    next_filters.pop("selected", None)
    href = f"/?{urlencode(next_filters)}"
    active = " active" if value == current_value else ""
    return (
        f'<a class="method-tab{active}" href="{_esc(href)}">'
        f'<span>{_esc(label)}</span><strong>{count}</strong></a>'
    )


def _param(params: dict[str, list[str]], key: str, default: str = "") -> str:
    values = params.get(key)
    return values[-1] if values else default


def _normalize_decision(value: str) -> str:
    if value in {"apply", "passed"}:
        return "approved"
    return value


def _date_param(params: dict[str, list[str]], key: str, default: str = "") -> str:
    if key not in params:
        return default
    return params[key][-1] if params[key] else ""


def _default_date_from() -> str:
    return (date.today() - timedelta(days=7)).isoformat()


def _all_history_href(query: str, decision: str, method: str) -> str:
    params = {"date_from": "", "date_to": ""}
    if query:
        params["q"] = query
    if decision != "all":
        params["decision"] = decision
    if method != "all":
        params["method"] = method
    return f"/?{urlencode(params)}"


def _today_href(query: str, decision: str, method: str) -> str:
    today = date.today().isoformat()
    params = {"date_from": today, "date_to": today}
    if query:
        params["q"] = query
    if decision != "all":
        params["decision"] = decision
    if method != "all":
        params["method"] = method
    return f"/?{urlencode(params)}"


def _seven_days_href(query: str, decision: str, method: str) -> str:
    params = {"date_from": _default_date_from(), "date_to": ""}
    if query:
        params["q"] = query
    if decision != "all":
        params["decision"] = decision
    if method != "all":
        params["method"] = method
    return f"/?{urlencode(params)}"


def _date_range_label(date_from: str, date_to: str) -> str:
    if date_from and date_to and date_from == date_to:
        return date_from
    if date_from and date_to:
        return f"{date_from} to {date_to}"
    if date_from:
        return f"Since {date_from}"
    if date_to:
        return f"Until {date_to}"
    return "All dates"


def _bool_label(value: bool) -> str:
    return "on" if value else "off"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


_CSS = """
:root {
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --text: #1d2430;
  --muted: #657184;
  --line: #d8dde6;
  --accent: #167b6b;
  --accent-dark: #0c5f52;
  --passed-bg: #eef3ff;
  --passed-text: #3156a3;
  --applied-bg: #e8f6ef;
  --applied-text: #126340;
  --hold-bg: #fff4d7;
  --hold-text: #805500;
  --reject-bg: #fbecec;
  --reject-text: #9a2d2d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  color: var(--text);
}
header {
  min-height: 56px;
  padding: 10px 28px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--line);
  background: var(--panel);
}
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 2px; font-size: 20px; font-weight: 700; }
h2 { font-size: 20px; line-height: 1.3; margin-bottom: 8px; }
h3 { margin: 22px 0 8px; font-size: 14px; text-transform: uppercase; color: var(--muted); }
header p, .meta, .muted, small { color: var(--muted); }
header p { margin-bottom: 0; font-size: 12px; }
main { padding: 14px 28px 28px; }
.decision-toolbar {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px;
  margin-bottom: 8px;
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: 8px;
  overflow-x: auto;
  overflow-y: hidden;
}
.toolbar-group {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 7px;
}
.status-group { flex: 1 0 auto; }
.method-group { flex: 0 0 auto; }
.toolbar-label {
  flex: 0 0 auto;
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}
.status-tabs {
  min-width: 0;
  display: flex;
  flex-wrap: nowrap;
  gap: 5px;
}
.tab {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 9px;
  color: var(--text);
  background: #fbfcfd;
  text-decoration: none;
  font-size: 12px;
}
.tab strong {
  min-width: 20px;
  min-height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 0 6px;
  background: #eef1f5;
  color: #526071;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.tab span { color: var(--muted); font-size: 12px; }
.tab.active {
  border-color: var(--accent);
  box-shadow: inset 0 0 0 1px var(--accent);
  background: #edf8f5;
}
.tab.active span { color: var(--accent-dark); font-weight: 700; }
.tab.active strong { background: #cfeee7; color: var(--accent-dark); }
.method-tabs {
  display: flex;
  flex-wrap: nowrap;
  gap: 5px;
}
.method-tab {
  min-height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 0 9px;
  color: var(--text);
  background: #fbfcfd;
  text-decoration: none;
  font-size: 12px;
}
.method-tab strong {
  min-width: 20px;
  min-height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 0 6px;
  background: #eef1f5;
  color: #526071;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.method-tab.active {
  border-color: var(--accent);
  background: #edf8f5;
  color: var(--accent-dark);
  font-weight: 700;
}
.method-tab.active strong { background: #cfeee7; color: var(--accent-dark); }
.filters {
  display: grid;
  grid-template-columns: minmax(240px, 1fr) 260px 96px 84px 84px 78px;
  gap: 10px;
  align-items: end;
  margin-bottom: 10px;
}
label, .date-field { display: grid; gap: 6px; font-size: 13px; color: var(--muted); }
.field-label { font-size: 13px; color: var(--muted); }
input, select {
  width: 100%;
  height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 10px;
  background: white;
  color: var(--text);
  font: inherit;
}
.date-picker { position: relative; }
.date-picker-toggle {
  width: 100%;
  justify-content: flex-start;
  color: var(--text);
  background: white;
}
.calendar-popover {
  position: absolute;
  z-index: 20;
  top: calc(100% + 8px);
  left: 0;
  width: 286px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: white;
  box-shadow: 0 16px 40px rgba(29, 36, 48, 0.16);
}
.calendar-head {
  display: grid;
  grid-template-columns: 34px 1fr 34px;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  color: var(--text);
}
.calendar-head strong { text-align: center; font-size: 14px; }
.calendar-nav {
  width: 34px;
  height: 30px;
  padding: 0;
  border-radius: 999px;
  font-size: 18px;
  line-height: 1;
}
.calendar-weekdays, .calendar-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 3px;
}
.calendar-weekdays {
  margin-bottom: 4px;
  color: var(--muted);
  font-size: 10px;
  font-weight: 800;
  text-align: center;
  text-transform: uppercase;
}
.calendar-day {
  width: 100%;
  height: 34px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text);
  font-size: 12px;
}
.calendar-day:hover { border-color: var(--accent); background: #edf8f5; }
.calendar-day.outside { color: #a3adba; }
.calendar-day.in-range {
  border-radius: 6px;
  background: #edf8f5;
  color: var(--accent-dark);
}
.calendar-day.selected {
  border-color: var(--accent-dark);
  background: var(--accent);
  color: white;
  font-weight: 800;
}
.calendar-day.today { box-shadow: inset 0 0 0 1px #9abfb6; }
button, .button, .shortcut-button {
  height: 38px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0 12px;
  color: var(--text);
  background: white;
  text-decoration: none;
  font: inherit;
  cursor: pointer;
}
.primary, button { background: var(--accent); color: white; border-color: var(--accent-dark); }
.shortcut-button {
  height: 34px;
  align-self: center;
  border-radius: 999px;
  border-color: #cfd8e3;
  background: #fbfcfd;
  color: #526071;
  font-size: 13px;
  font-weight: 700;
}
.shortcut-button:hover {
  border-color: var(--accent);
  color: var(--accent-dark);
  background: #edf8f5;
}
.date-picker button.date-picker-toggle {
  justify-content: flex-start;
  border-color: var(--line);
  background: white;
  color: var(--text);
}
.calendar-popover button.calendar-nav {
  border-color: var(--line);
  background: white;
  color: var(--text);
}
.calendar-popover button.calendar-day {
  height: 34px;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 999px;
  background: transparent;
  color: var(--text);
}
.calendar-popover button.calendar-day:hover { border-color: var(--accent); background: #edf8f5; }
.calendar-popover button.calendar-day.outside { color: #a3adba; }
.calendar-popover button.calendar-day.in-range {
  border-radius: 6px;
  background: #edf8f5;
  color: var(--accent-dark);
}
.calendar-popover button.calendar-day.selected {
  border-color: var(--accent-dark);
  background: var(--accent);
  color: white;
  font-weight: 800;
}
.workspace {
  display: grid;
  grid-template-columns: minmax(320px, 0.9fr) minmax(420px, 1.3fr);
  gap: 16px;
  align-items: start;
  height: calc(100vh - 188px);
  min-height: 520px;
}
.list, .detail {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  height: 100%;
  overflow-y: auto;
}
.detail { padding: 20px; }
.row {
  display: block;
  padding: 14px;
  border-bottom: 1px solid var(--line);
  color: var(--text);
  text-decoration: none;
}
.row:hover { background: #f9fafb; }
.row.selected {
  background: #edf8f5;
  border-left: 4px solid var(--accent);
  padding-left: 10px;
}
.row.selected strong { color: var(--accent-dark); }
.row strong { display: block; margin: 8px 0 6px; line-height: 1.35; }
.row-top, .detail-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.row-labels {
  min-width: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.label-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0 0 7px;
}
.row-labels .label-strip { margin: 0; }
.detail-labels { margin: 0 0 10px; }
.project-label {
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  border: 1px solid #d5dde8;
  border-radius: 999px;
  padding: 0 8px;
  background: #f8fafc;
  color: #526071;
  font-size: 11px;
  font-weight: 800;
}
.pill {
  min-width: 62px;
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 0 10px;
  font-size: 12px;
  font-weight: 700;
}
.passed { background: var(--passed-bg); color: var(--passed-text); }
.applied { background: var(--applied-bg); color: var(--applied-text); }
.hold { background: var(--hold-bg); color: var(--hold-text); }
.reject { background: var(--reject-bg); color: var(--reject-text); }
.score { font-variant-numeric: tabular-nums; color: var(--muted); font-weight: 700; }
.score.large { font-size: 28px; color: var(--text); }
ul { padding-left: 20px; }
li { margin: 7px 0; line-height: 1.45; }
dl {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 8px 12px;
  margin: 0 0 16px;
}
dt { color: var(--muted); }
dd { margin: 0; }
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: #fbfcfd;
  line-height: 1.45;
}
.empty { padding: 24px; color: var(--muted); }
@media (max-width: 860px) {
  header { padding: 16px; align-items: flex-start; gap: 12px; }
  main { padding: 16px; }
  .filters, .workspace { grid-template-columns: 1fr; }
  .calendar-popover { width: min(286px, calc(100vw - 32px)); }
  .decision-toolbar, .toolbar-group { align-items: center; }
  .workspace { height: auto; min-height: 0; }
  .list, .detail { height: auto; max-height: none; }
}
"""


_JS = """
(function () {
  var list = document.getElementById("decision-list");
  if (list) {
    var scrollKey = "backstageDecisionListScroll";
    var filterKey = "backstageDecisionListFilter";
    var params = new URLSearchParams(window.location.search);
    var selected = params.get("selected");
    params.delete("selected");
    var currentFilter = params.toString();
    var savedScroll = sessionStorage.getItem(scrollKey);
    var savedFilter = sessionStorage.getItem(filterKey);
    if (selected && savedScroll !== null && savedFilter === currentFilter) {
      list.scrollTop = Number(savedScroll) || 0;
    } else {
      sessionStorage.removeItem(scrollKey);
      sessionStorage.removeItem(filterKey);
      list.scrollTop = 0;
    }
    list.addEventListener("click", function (event) {
      var row = event.target.closest("[data-decision-row]");
      if (!row) return;
      sessionStorage.setItem(scrollKey, String(list.scrollTop));
      sessionStorage.setItem(filterKey, currentFilter);
    });
  }

  var picker = document.querySelector("[data-date-picker]");
  if (!picker) return;

  var toggle = picker.querySelector(".date-picker-toggle");
  var popover = picker.querySelector("[data-calendar-popover]");
  var fromInput = picker.querySelector("[data-date-from]");
  var toInput = picker.querySelector("[data-date-to]");
  var label = picker.querySelector("[data-range-label]");
  var monthLabel = picker.querySelector("[data-month-label]");
  var grid = picker.querySelector("[data-calendar-grid]");
  var todayIso = toIso(new Date());
  var clickCount = 0;
  var viewDate = parseIso(fromInput.value || toInput.value || todayIso) || new Date();
  viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function toIso(date) {
    return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
  }

  function parseIso(value) {
    if (!value) return null;
    var parts = value.split("-").map(Number);
    if (parts.length !== 3 || parts.some(isNaN)) return null;
    return new Date(parts[0], parts[1] - 1, parts[2]);
  }

  function compareIso(left, right) {
    if (left === right) return 0;
    return left < right ? -1 : 1;
  }

  function setRange(first, second) {
    if (!first && !second) {
      fromInput.value = "";
      toInput.value = "";
      updateLabel();
      return;
    }
    if (!second || first === second) {
      fromInput.value = first;
      toInput.value = first;
      updateLabel();
      return;
    }
    if (compareIso(first, second) <= 0) {
      fromInput.value = first;
      toInput.value = second;
    } else {
      fromInput.value = second;
      toInput.value = first;
    }
    updateLabel();
  }

  function updateLabel() {
    if (fromInput.value && toInput.value && fromInput.value === toInput.value) {
      label.textContent = fromInput.value;
    } else if (fromInput.value && toInput.value) {
      label.textContent = fromInput.value + " to " + toInput.value;
    } else if (fromInput.value) {
      label.textContent = "Since " + fromInput.value;
    } else if (toInput.value) {
      label.textContent = "Until " + toInput.value;
    } else {
      label.textContent = "All dates";
    }
  }

  function isInRange(dayIso) {
    return fromInput.value && toInput.value && compareIso(fromInput.value, dayIso) <= 0 && compareIso(dayIso, toInput.value) <= 0;
  }

  function renderCalendar() {
    var formatter = new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" });
    monthLabel.textContent = formatter.format(viewDate);
    grid.innerHTML = "";

    var first = new Date(viewDate.getFullYear(), viewDate.getMonth(), 1);
    var start = new Date(first);
    start.setDate(first.getDate() - first.getDay());

    for (var i = 0; i < 42; i += 1) {
      var day = new Date(start);
      day.setDate(start.getDate() + i);
      var dayIso = toIso(day);
      var button = document.createElement("button");
      button.type = "button";
      button.className = "calendar-day";
      button.textContent = String(day.getDate());
      button.dataset.date = dayIso;
      if (day.getMonth() !== viewDate.getMonth()) button.classList.add("outside");
      if (dayIso === todayIso) button.classList.add("today");
      if (isInRange(dayIso)) button.classList.add("in-range");
      if (dayIso === fromInput.value || dayIso === toInput.value) button.classList.add("selected");
      grid.appendChild(button);
    }
  }

  toggle.addEventListener("click", function () {
    var willOpen = popover.hasAttribute("hidden");
    popover.toggleAttribute("hidden", !willOpen);
    toggle.setAttribute("aria-expanded", String(willOpen));
    if (willOpen) renderCalendar();
  });

  picker.querySelector("[data-prev-month]").addEventListener("click", function () {
    viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() - 1, 1);
    renderCalendar();
  });

  picker.querySelector("[data-next-month]").addEventListener("click", function () {
    viewDate = new Date(viewDate.getFullYear(), viewDate.getMonth() + 1, 1);
    renderCalendar();
  });

  grid.addEventListener("click", function (event) {
    var button = event.target.closest(".calendar-day");
    if (!button) return;
    var picked = button.dataset.date;
    if (clickCount === 0 || clickCount >= 2) {
      setRange(picked, picked);
      clickCount = 1;
    } else {
      setRange(fromInput.value, picked);
      clickCount = 2;
    }
    renderCalendar();
  });

  document.addEventListener("click", function (event) {
    if (picker.contains(event.target)) return;
    popover.setAttribute("hidden", "");
    toggle.setAttribute("aria-expanded", "false");
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    popover.setAttribute("hidden", "");
    toggle.setAttribute("aria-expanded", "false");
  });

  updateLabel();
  renderCalendar();
})();
"""
