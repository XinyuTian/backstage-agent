from __future__ import annotations

import html
import json
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

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
    decision = _param(params, "decision", "all")
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
      <label>Project Date From<input type="date" name="date_from" value="{_esc(date_from)}"></label>
      <label>Project Date To<input type="date" name="date_to" value="{_esc(date_to)}"></label>
      <input type="hidden" name="decision" value="{_esc(decision)}">
      <input type="hidden" name="method" value="{_esc(method)}">
      <button type="submit">Search</button>
      <a class="shortcut-button" href="{_esc(today_href)}">Today</a>
      <a class="shortcut-button" href="{_esc(history_href)}">All</a>
    </form>
    <section class="decision-toolbar" aria-label="Dashboard filters">
      <div class="toolbar-group status-group">
        <span class="toolbar-label">Status</span>
        <nav class="status-tabs" aria-label="Decision status">
          {_tab("All", counts["total"] or 0, "decision", "all", decision, base_filters)}
          {_tab("Apply", counts["apply_count"] or 0, "decision", "apply", decision, base_filters)}
          {_tab("Reject", counts["reject_count"] or 0, "decision", "reject", decision, base_filters)}
          {_tab("Skipped", counts["skipped_count"] or 0, "decision", "skipped", decision, base_filters)}
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
    selected_class = " selected" if str(row["id"]) == selected_id else ""
    return f"""
    <a class="row{selected_class}" href="{_esc(href)}" data-decision-row="{_esc(row["id"])}">
      <div class="row-top">
        <span class="pill {status_class}">{status}</span>
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
    return f"""
      <div class="detail-header">
        <span class="pill {status_class}">{status}</span>
        <span class="score large">{float(row["score"]):.2f}</span>
      </div>
      <h2>{_esc(row["title"])}</h2>
      <div class="meta">Project date {_esc(_project_date(row))} · scanned {_esc(row["created_at"])} · {_screening_label(row)}</div>
      {_link(url)}
      <h3>Reasons</h3>
      {_list(reasons)}
      <h3>Concerns</h3>
      {_list(concerns) if concerns else '<p class="muted">None recorded.</p>'}
      <h3>Parsed Notice</h3>
      <dl>
        {_field("Project", notice.get("project"))}
        {_field("Role", notice.get("role"))}
        {_field("Location", notice.get("location"))}
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


def _decision_status(row) -> tuple[str, str]:
    if row["should_apply"]:
        return "Apply", "apply"
    reasons = json.loads(row["reasons_json"])
    if any("Skipped LLM screening" in reason for reason in reasons):
        return "Skipped", "skipped"
    return "Reject", "reject"


def _screening_label(row) -> str:
    return "LLM screening" if row["llm_used"] else "Local rule screening"


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
  --apply-bg: #e8f6ef;
  --apply-text: #126340;
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
  grid-template-columns: minmax(240px, 1fr) 150px 150px 96px 86px 112px;
  gap: 10px;
  align-items: end;
  margin-bottom: 10px;
}
label { display: grid; gap: 6px; font-size: 13px; color: var(--muted); }
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
.apply { background: var(--apply-bg); color: var(--apply-text); }
.reject { background: var(--reject-bg); color: var(--reject-text); }
.skipped { background: #eef1f5; color: #526071; }
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
  .decision-toolbar, .toolbar-group { align-items: center; }
  .workspace { height: auto; min-height: 0; }
  .list, .detail { height: auto; max-height: none; }
}
"""


_JS = """
(function () {
  var list = document.getElementById("decision-list");
  if (!list) return;
  var scrollKey = "backstageDecisionListScroll";
  var savedScroll = sessionStorage.getItem(scrollKey);
  if (savedScroll !== null) {
    list.scrollTop = Number(savedScroll) || 0;
  }
  list.addEventListener("click", function (event) {
    var row = event.target.closest("[data-decision-row]");
    if (!row) return;
    sessionStorage.setItem(scrollKey, String(list.scrollTop));
  });
})();
"""
