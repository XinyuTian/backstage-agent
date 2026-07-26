# Compact Candidate Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the compact green candidate header, add subject-date navigation, simplify extracted evidence, and replace the vertical correction editor with a bottom-anchored spreadsheet grid.

**Architecture:** Keep the current server-rendered Python UI and correction persistence. Add date-window parameters to the existing storage query, carry those parameters through links and redirects, and reshape only the HTML/CSS/JavaScript presentation. Preserve parser output and make subject-derived `project_date` the first-choice workbench date.

**Tech Stack:** Python 3, SQLite, `http.server`, server-rendered HTML/CSS/JavaScript, pytest.

## Global Constraints

- Do not change scoring rules, score calculation, SQLite schema, scan scheduling, or notifications.
- Keep `Project name — Role name` in both workbench panels.
- Preserve server-side correction range, identity, component, and snapshot validation.
- Preserve unrelated working-tree changes.
- Use test-driven development: add each regression test and observe the expected failure before production edits.

---

### Task 1: Subject-Derived Candidate Dates and Date-Window Querying

**Files:**
- Modify: `tests/test_parser.py`
- Modify: `tests/test_candidate_storage.py`
- Modify: `src/backstage_agent/storage.py:341-387`

**Interfaces:**
- Consumes: `ProjectNotice.project_date` already populated by `parser._date_from_email_subject`.
- Produces: `DecisionStore.search_candidate_workbench_rows(query="", band="all", date_end="", days=1, limit=200) -> list[sqlite3.Row]`.
- Produces: each result's `effective_project_date`, with `projects.project_date` taking precedence over `last_seen_date` and `created_at`.

- [ ] **Step 1: Add a parser regression assertion**

Add a focused test using:

```python
EmailMessage(
    subject="4 New Roles Available for basic filter - Jul 23",
    received_at=datetime(2026, 7, 24, 9, 0),
    text="Project: Example\nRole: Lead",
)
```

Assert that every parsed notice has `project_date == date(2026, 7, 23)`.

- [ ] **Step 2: Run the parser regression**

Run:

```bash
.venv/bin/python -m pytest tests/test_parser.py -q
```

Expected: PASS, confirming the parser already provides the required subject date.

- [ ] **Step 3: Add failing storage tests**

Extend the workbench storage fixture with candidates whose project rows have:

```python
project_date=date(2026, 7, 23)
last_seen_date=date(2026, 7, 24)
```

Assert:

```python
rows = store.search_candidate_workbench_rows(date_end="2026-07-23", days=1)
assert [row["effective_project_date"] for row in rows] == ["2026-07-23"]

rows = store.search_candidate_workbench_rows(date_end="2026-07-24", days=7)
assert {row["effective_project_date"] for row in rows} == {
    "2026-07-18",
    "2026-07-23",
}
```

Also assert an exact-day query excludes candidates outside that date.

- [ ] **Step 4: Run the storage tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_storage.py -k "workbench_rows" -q
```

Expected: FAIL because `date_end` and `days` are not accepted and `last_seen_date` currently takes precedence.

- [ ] **Step 5: Implement date precedence and filtering**

Change the method signature to:

```python
def search_candidate_workbench_rows(
    self,
    query: str = "",
    band: str = "all",
    date_end: str = "",
    days: int = 1,
    limit: int = 200,
) -> list[sqlite3.Row]:
```

Use this SQL date expression consistently:

```sql
date(COALESCE(p.project_date, p.last_seen_date, p.created_at))
```

When `date_end` is non-empty, append:

```sql
date(COALESCE(p.project_date, p.last_seen_date, p.created_at))
BETWEEN date(?, '-' || (? - 1) || ' days') AND date(?)
```

Bind `date_end`, a clamped `days` value of either `1` or `7`, and `date_end`.

- [ ] **Step 6: Run storage tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_storage.py -k "workbench_rows" -q
```

Expected: all selected tests pass.

### Task 2: Compact Filters and Date Navigation

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py:121-165`
- Modify: `src/backstage_agent/ui.py:408-440`
- Modify: `src/backstage_agent/ui.py:620-650`

**Interfaces:**
- Consumes: query parameters `q`, `date`, and `days`.
- Produces: `_date_filter_context(params) -> tuple[str, int]`, where date is ISO `YYYY-MM-DD` and days is `1` or `7`.
- Produces: workbench links and correction redirects that preserve `q`, `date`, and `days`.

- [ ] **Step 1: Add failing filter-control tests**

Update `FakeStore.search_candidate_workbench_rows` to record `date_end` and `days`.
Render with:

```python
{"q": ["summer"], "date": ["2026-07-23"], "days": ["1"]}
```

Assert the HTML:

```python
assert "<h1>Backstage Candidates</h1>" in html
assert "Ranked mutual-selection scores and calibration feedback" not in html
assert 'placeholder="Search project or role"' in html
assert '>Search<' not in html
assert '>Date<' not in html
assert "Today" in html
assert "7 days" in html
assert 'aria-label="Previous day"' in html
assert 'aria-label="Next day"' in html
```

Assert selected-candidate links and correction forms carry `date=2026-07-23` and `days=1`.

- [ ] **Step 2: Run the UI tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "filter or workbench" -q
```

Expected: FAIL because the date controls and query context do not exist.

- [ ] **Step 3: Implement filter parsing and navigation**

Add helpers that:

- accept only valid ISO dates and otherwise use `date.today().isoformat()`;
- normalize `days` to `7` only when the query value is `"7"`, otherwise `1`;
- calculate previous and next ISO dates with `timedelta(days=1)`;
- produce query URLs with `urlencode`.

Render controls in this order:

```text
search input, date input, ←, Today, →, 7 days, Filter
```

Use placeholders/ARIA labels instead of visible Search and Date labels. Pass
`date_end` and `days` to `search_candidate_workbench_rows`.

- [ ] **Step 4: Preserve date context**

Extend `_render_workbench`, `_render_candidate_list_item`,
`_render_candidate_detail`, `_render_component_row`, `_hidden_context`, and
`_correction_redirect` to carry `date` and `days`.

- [ ] **Step 5: Run UI tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "filter or workbench" -q
```

Expected: all selected tests pass.

### Task 3: Simplified Evidence and Spreadsheet Correction Grid

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py:442-590`
- Modify: `src/backstage_agent/ui.py:700-end`

**Interfaces:**
- Consumes: the existing workbench view's `title`, `display_overall`, `features`, `components`, `warnings`, and correction metadata.
- Produces: `_render_component_grid(view, query, date_end, days) -> str`.
- Preserves: existing POST routes for save, reset, and reconfirm.

- [ ] **Step 1: Add failing structural tests**

Assert the rendered detail contains:

```python
assert "Summer Play — Lead" in html
assert 'class="evidence-pane"' in html
assert "Extracted features" in html
assert 'class="correction-grid"' in html
assert "Agent score" in html
assert "Your correction" in html
```

Assert it excludes:

```python
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
```

Use an HTML parser to assert the grid contains one header row and exactly two
data rows, with one component column per score component.

- [ ] **Step 2: Run the structural tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "render or grid or warning" -q
```

Expected: FAIL against the current vertical component editor.

- [ ] **Step 3: Simplify the detail heading and evidence**

Render only:

```html
<h2>{project name — role name}</h2>
<strong class="detail-score" data-overall>{display score}</strong>
```

Render `Extracted features` plus relevant structured requirement information
inside the flexible, scrollable evidence pane. Do not render `notice`,
drivers, trace, caps, band labels, candidate type, or the compatible-snapshot
warning. Keep incompatible-snapshot safety represented by disabled inputs.

- [ ] **Step 4: Implement the two-row grid**

Render semantic table markup:

```html
<table class="correction-grid">
  <thead><tr><th></th><!-- component names --></tr></thead>
  <tbody>
    <tr><th>Agent score</th><!-- score / maximum --></tr>
    <tr><th>Your correction</th><!-- component forms --></tr>
  </tbody>
</table>
```

Each component cell contains one form with hidden context, numeric correction
input, feedback/reason input, and compact reset/reconfirm controls only when
needed. The table wrapper owns horizontal scrolling and remains the final child
of the right panel.

- [ ] **Step 5: Add Enter-to-save JavaScript**

Attach a `keydown` listener to correction and feedback inputs:

```javascript
if (event.key === "Enter") {
  event.preventDefault();
  event.currentTarget.form.requestSubmit();
}
```

When a numeric input becomes non-empty, enable/focus its sibling feedback
input. Do not display instructional text.

- [ ] **Step 6: Replace CSS with the approved compact layout**

Restore the old green header colors, reduce header/filter padding, keep the
29/71 left/right split, give `.evidence-pane` the flexible remaining height,
and anchor the grid wrapper at the bottom. Use square spreadsheet borders and
small inputs instead of cards/pills.

- [ ] **Step 7: Run UI tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -q
```

Expected: all candidate UI tests pass, including existing save/reset/reconfirm
validation tests.

### Task 4: Documentation and End-to-End Verification

**Files:**
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/module-guide.md`

**Interfaces:**
- Consumes: completed parser/storage/UI behavior.
- Produces: current repository documentation and fresh verification evidence.

- [ ] **Step 1: Update documentation**

In `PROJECT_STATE.md`, describe the compact date-filtered candidate workbench
and spreadsheet corrections. In `CHANGELOG.md`, add concise Unreleased entries
for the subject-date precedence and compact UI. In `docs/module-guide.md`,
document the exact-day/seven-day filters and subject-derived workbench date.

- [ ] **Step 2: Run targeted tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_parser.py tests/test_candidate_storage.py tests/test_ui_candidates.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Run the full suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Inspect generated HTML**

Render `_render_candidates_index` with fixture data and verify the generated
HTML contains the green header, date controls, simplified evidence, and
two-row grid, while excluding the removed copy and sections.

- [ ] **Step 5: Verify the live dashboard**

Restart the launchd-managed dashboard through the existing recovery script,
open `http://127.0.0.1:8765/candidates`, and verify:

- the listener serves the current checkout;
- date navigation changes the visible date/window;
- the grid remains at the bottom while evidence uses the upper area;
- Enter saves a correction and the saved value survives reload.

Do not run a scan, contact Backstage, or deliver a notification.

- [ ] **Step 6: Review the final diff**

Run:

```bash
git status --short
git diff --check
git diff -- src/backstage_agent/storage.py src/backstage_agent/ui.py tests/test_parser.py tests/test_candidate_storage.py tests/test_ui_candidates.py PROJECT_STATE.md CHANGELOG.md docs/module-guide.md
```

Confirm no unrelated user-owned files were modified.
