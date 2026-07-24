# Legacy System Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all active legacy screening, review, decision, application, and decision-dashboard code while leaving existing SQLite records untouched.

**Architecture:** Reduce the agent and CLI contracts to ingestion plus candidate scoring, move the three still-needed project-context enrichment helpers out of the legacy project screener, and make the dashboard candidate-only. Remove legacy runtime storage methods but retain legacy table creation as a non-destructive compatibility boundary for existing databases.

**Tech Stack:** Python 3, dataclasses, argparse, SQLite, `http.server`, pytest, zsh launchd wrapper.

## Global Constraints

- Do not execute `DROP TABLE`, `DELETE`, destructive migrations, database compaction, or active-database cleanup.
- Preserve projects, roles, candidates, candidate feedback, calibration proposals, and all candidate scoring behavior.
- Preserve one-day scheduling, 9:00-12:00 retries, macOS notification handling, dashboard recovery, Backstage fetching, scoring fallbacks, score preservation, and explicit overwrite semantics.
- Do not run live IMAP, Backstage browser, model-provider, macOS notification, or launchd actions.
- Preserve unrelated untracked files.

## File Structure

- Create `src/backstage_agent/project_context.py`: scoring-era project enrichment helpers moved from the legacy project screener.
- Modify `src/backstage_agent/agent.py`: scoring-only dependencies and `ScanResult`.
- Modify `src/backstage_agent/models.py`: shared ingestion/profile models only.
- Modify `src/backstage_agent/cli.py`: scoring-only commands and scan JSON.
- Modify `src/backstage_agent/ui.py`: candidate-only routes and rendering.
- Modify `src/backstage_agent/storage.py`: active candidate/project/role persistence plus inert legacy table compatibility.
- Modify `src/backstage_agent/settings.py`, `.env.example`, and `tests/conftest.py`: remove legacy-only settings.
- Delete legacy modules and dedicated tests listed in Tasks 1-4.
- Modify repository documentation in Task 5.

---

### Task 1: Remove Legacy Services From Agent and Models

**Files:**
- Create: `src/backstage_agent/project_context.py`
- Modify: `src/backstage_agent/agent.py`
- Modify: `src/backstage_agent/models.py`
- Modify: `tests/test_agent_review_gate.py`
- Modify: `tests/test_agent_candidate_scoring.py`
- Modify: `src/backstage_agent/project_screener.py` (temporary storage-compatibility constant only)
- Delete: `src/backstage_agent/screener.py`
- Delete: `src/backstage_agent/reviewer.py`
- Delete: `src/backstage_agent/decision_core.py`
- Delete: `src/backstage_agent/application.py`
- Delete: `tests/test_project_screener.py`
- Delete: `tests/test_screener.py`
- Delete: `tests/test_structured_screening.py`
- Delete: `tests/test_structured_reviewer.py`
- Delete: `tests/test_decision_core.py`
- Delete: `tests/test_application.py`
- Delete: `tests/test_screening_preferences.py`

**Interfaces:**
- Consumes: `ProjectNotice`, `CastingNotice`, and `project_page_context()`
- Produces: `with_project_page_context(project, context)`, `with_project_role_context(project, roles)`, `with_project_shooting_info(project, locations, dates)`, and scoring-only `ScanResult`

- [ ] **Step 1: Write failing scoring-only agent contract tests**

Replace legacy fake services in `tests/test_agent_review_gate.py` with a minimal
agent fixture and assert:

```python
def test_scoring_agent_has_no_legacy_services(scoring_agent):
    for name in ("project_screener", "screener", "reviewer", "applications"):
        assert not hasattr(scoring_agent, name)


def test_scan_result_contains_only_ingestion_and_scoring_fields(scoring_agent):
    result = scoring_agent.scan(limit=1, target_date=date(2026, 7, 24))
    assert set(result.__dataclass_fields__) == {
        "messages_seen",
        "projects_seen",
        "notices_seen",
        "candidates_scored",
        "candidates_skipped_existing",
        "draft_suggestions",
    }
```

Update `tests/test_agent_candidate_scoring.py` to remove fake project screener,
reviewer, `ScreeningDecision`, `ReviewDecision`, and `project_to_notice`
dependencies. Candidate scores must retain the same expected values and ranking
identities.

- [ ] **Step 2: Run agent tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_agent_review_gate.py tests/test_agent_candidate_scoring.py -v
```

Expected: FAIL because the agent still exposes legacy services and result fields.

- [ ] **Step 3: Move project enrichment helpers**

Create `project_context.py` with the existing implementations of:

```python
def with_project_role_context(
    project: ProjectNotice,
    roles: list[CastingNotice],
) -> ProjectNotice:
    context_parts = []
    compensations = [
        compensation.strip()
        for role in roles
        if (compensation := role.compensation) and compensation.strip()
    ]
    if compensations:
        context_parts.append(f"Role compensation: {'; '.join(dict.fromkeys(compensations))}")
    role_summaries = [
        f"{role.role}: {role.description}"
        for role in roles[:4]
        if role.role and role.description
    ]
    if role_summaries:
        context_parts.append("Role summaries: " + " | ".join(role_summaries))
    if not context_parts:
        return project
    added_context = "\n".join(context_parts)
    return replace(
        project,
        description="\n".join([project.description, added_context]).strip(),
        raw_text="\n".join([project.raw_text, added_context]).strip(),
    )

def with_project_page_context(project: ProjectNotice, page_context: str) -> ProjectNotice:
    page_context = page_context.strip()
    if not page_context or page_context in project.raw_text:
        return project
    return replace(
        project,
        description="\n".join([project.description, page_context]).strip(),
        raw_text="\n".join([project.raw_text, page_context]).strip(),
    )

def with_project_shooting_info(
    project: ProjectNotice,
    shooting_locations: str | None,
    shooting_dates: str | None,
) -> ProjectNotice:
    if not shooting_locations and not shooting_dates:
        return project
    return replace(
        project,
        shooting_locations=shooting_locations or project.shooting_locations,
        shooting_dates=shooting_dates or project.shooting_dates,
    )
```

Copy only enrichment behavior; do not copy project-gate constants, decision
conversion, LLM prompts, local screening, or screening policy.

- [ ] **Step 4: Simplify the agent and models**

In `agent.py`, import enrichment helpers from `project_context`, remove legacy
service construction/imports and project-evaluation scoring parameters, then
define:

```python
@dataclass(frozen=True)
class ScanResult:
    messages_seen: int
    projects_seen: int
    notices_seen: int
    candidates_scored: int = 0
    candidates_skipped_existing: int = 0
    draft_suggestions: int = 0
```

Make `_score_candidate_with_fallback(candidate)` depend only on feature
extraction, requirement matching, scoring rules, and actor profile. Delete
`_should_review`, `_review_allows_next_step`,
`_with_project_evaluation_context`, and the unused per-project ranking helper.

Delete `ScreeningDecision`, `ReviewDecision`, and `ApplicationDraft` from
`models.py`.

- [ ] **Step 5: Delete legacy modules and dedicated tests**

Delete `screener.py`, `reviewer.py`, `decision_core.py`, and `application.py`.
Reduce `project_screener.py` temporarily to:

```python
"""Temporary legacy schema constant; removed with legacy storage in Task 4."""

PROJECT_GATE_ROLE = "__project_gate__"
```

This keeps the untouched legacy decision SQL importable until Task 4 removes
that SQL. Delete every dedicated test listed in this task. Then run:

```bash
rg -n "project_screener|RoleScreener|DecisionReviewer|ApplicationService|DecisionBucket|ScreeningDecision|ReviewDecision|ApplicationDraft" src/backstage_agent tests
```

Expected: remaining matches are limited to the temporary project-gate constant
and storage/UI/CLI work scheduled for later tasks; no agent or
candidate-scoring match remains.

- [ ] **Step 6: Run agent and scoring tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_agent_review_gate.py tests/test_agent_candidate_scoring.py tests/test_candidate_scoring.py tests/test_candidate_generation.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/backstage_agent tests
git commit -m "refactor: remove legacy selection services"
```

---

### Task 2: Remove Legacy CLI and Settings Contracts

**Files:**
- Modify: `src/backstage_agent/cli.py`
- Modify: `src/backstage_agent/settings.py`
- Modify: `.env.example`
- Modify: `tests/test_cli_summary.py`
- Modify: `tests/conftest.py`

**Interfaces:**
- Consumes: scoring-only `ScanResult`
- Produces: scoring-only scan JSON and command parser

- [ ] **Step 1: Write failing CLI contract tests**

Add a parser-construction helper `build_parser()` to the desired CLI interface,
then test:

```python
def test_cli_has_no_decisions_command():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["decisions"])


def test_scan_payload_has_only_scoring_counts(monkeypatch, capsys):
    _scan(25, 1, "2026-07-24", False)
    payload = json.loads(capsys.readouterr().out)
    for key in ("project_decisions", "project_reviews", "decisions", "reviews", "applications"):
        assert key not in payload
```

Keep existing scoring summary assertions.

- [ ] **Step 2: Run CLI tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_summary.py tests/test_cli_candidates.py -v
```

Expected: FAIL because the command and legacy JSON keys remain.

- [ ] **Step 3: Simplify CLI and settings**

Refactor `main()` to call `build_parser()`, remove the `decisions` parser,
dispatch, `_decisions`, `_bucket_summary`, `_budget_warnings`, and legacy
imports. Remove legacy count keys and `dry_run` from scan JSON.

Remove `min_match_score`, `dry_run`, `reviewer_provider`, `reviewer_model`, and
`max_reviewer_calls_per_scan` from `Settings`, `load_settings()`,
`_show_config()`, `.env.example`, and `tests/conftest.py`. Keep LLM settings
used by `FeatureExtractor`.

- [ ] **Step 4: Run CLI, settings, feature, and scheduling tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_summary.py tests/test_cli_candidates.py tests/test_feature_extractor.py tests/test_daily_scan_script.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/cli.py src/backstage_agent/settings.py .env.example tests/test_cli_summary.py tests/conftest.py
git commit -m "refactor: remove legacy cli contracts"
```

---

### Task 3: Make the Dashboard Candidate-Only

**Files:**
- Modify: `src/backstage_agent/ui.py`
- Modify: `tests/test_ui_candidates.py`
- Delete: `tests/test_ui_labels.py`

**Interfaces:**
- Consumes: `DecisionStore.search_candidates()` and `record_candidate_feedback()`
- Produces: `_get_route(path: str) -> tuple[str, str | None]`, `_post_route(path: str) -> str | None`, `GET / -> 303 /candidates`, `GET /candidates -> 200`, `POST /candidate-feedback -> 303`, and no cover-letter route

- [ ] **Step 1: Add failing route-level tests**

Add pure route classifiers so routing is tested without binding a real port:

```python
def test_root_redirects_to_candidates():
    assert _get_route("/") == ("redirect", "/candidates")


def test_candidate_routes_exclude_cover_letter():
    assert _get_route("/candidates") == ("candidates", None)
    assert _post_route("/candidate-feedback") == "candidate_feedback"
    assert _post_route("/cover-letter") is None
```

Retain the existing candidate rendering and feedback tests.

- [ ] **Step 2: Run UI tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -v
```

Expected: FAIL because `/` renders decisions and `/cover-letter` is active.

- [ ] **Step 3: Remove decision UI**

Implement:

```python
def _get_route(path: str) -> tuple[str, str | None]:
    if path == "/":
        return "redirect", "/candidates"
    if path == "/candidates":
        return "candidates", None
    return "not_found", None


def _post_route(path: str) -> str | None:
    return "candidate_feedback" if path == "/candidate-feedback" else None
```

Keep only candidate-related imports and helpers. In the handler:

```python
if parsed.path == "/":
    self.send_response(303)
    self.send_header("Location", "/candidates")
    self.end_headers()
    return
if parsed.path == "/candidates":
    self._send_html(_render_candidates_index(store, parse_qs(parsed.query)))
    return
```

The only POST route is `/candidate-feedback`. Delete decision rendering,
filtering, counts, detail panels, application links, cover-letter conversion,
decision status, reviewer, project-gate, date-filter, and legacy JSON helpers.
Change the startup message to
`Candidate UI running at http://{self.host}:{self.port}`.

- [ ] **Step 4: Delete legacy UI tests and run candidate UI tests**

Delete `tests/test_ui_labels.py`, then run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/ui.py tests/test_ui_candidates.py tests/test_ui_labels.py
git commit -m "refactor: make dashboard candidate only"
```

---

### Task 4: Remove Legacy Runtime Storage While Preserving Rows

**Files:**
- Modify: `src/backstage_agent/storage.py`
- Delete: `src/backstage_agent/project_screener.py`
- Modify: `tests/test_candidate_storage.py`
- Delete: `tests/test_storage_dashboard.py`

**Interfaces:**
- Consumes: existing databases that may contain `decisions`, `reviews`, and `applications`
- Produces: candidate/project/role storage with no legacy runtime readers or writers

- [ ] **Step 1: Add a preservation test**

Create a disposable database, insert sentinel legacy rows with raw SQL, open it
through `DecisionStore`, perform candidate storage, and assert:

```python
with sqlite3.connect(path) as connection:
    assert connection.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
```

Also assert these methods are absent:

```python
for name in (
    "record_decision",
    "record_review",
    "record_application",
    "recent_decisions",
    "get_decision",
    "search_decisions",
    "decision_counts",
    "screening_counts",
):
    assert not hasattr(store, name)
```

- [ ] **Step 2: Run storage tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_storage.py -v
```

Expected: FAIL because legacy methods remain.

- [ ] **Step 3: Remove legacy runtime storage**

Remove legacy model imports and all methods listed in Step 1, plus their
decision-filter SQL helpers and project-gate dependencies. Retain the
`CREATE TABLE IF NOT EXISTS decisions`, reviews, and applications compatibility
schema and additive column guards so existing databases open without mutation
beyond current non-destructive schema checks.

Delete `project_screener.py` and `tests/test_storage_dashboard.py`.

- [ ] **Step 4: Run storage and end-to-end scoring tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_storage.py tests/test_agent_candidate_scoring.py tests/test_ui_candidates.py -v
```

Expected: PASS, including sentinel legacy-row preservation.

- [ ] **Step 5: Commit**

```bash
git add src/backstage_agent/storage.py tests/test_candidate_storage.py tests/test_storage_dashboard.py
git commit -m "refactor: retire legacy runtime storage"
```

---

### Task 5: Remove Stale References, Document, Verify, and Merge

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/module-guide.md`
- Modify: `pyproject.toml` only if package metadata describes legacy behavior

**Interfaces:**
- Consumes: completed scoring-only product
- Produces: accurate documentation and local `main` integration

- [ ] **Step 1: Update documentation**

State consistently:

```text
Backstage Agent refreshes casting projects and roles, scores and ranks
candidates, records feedback, and proposes calibration changes.

Legacy screening, review, application drafting, decision CLI, and decision
dashboard code have been removed. Existing legacy SQLite rows are left untouched
but are no longer read or written by the application.
```

Set `PROJECT_STATE.md` to `Last updated: 2026-07-24`. Remove live-submission,
dry-run, reviewer, decision-bucket, application-drafting, and legacy-removal
follow-up claims.

- [ ] **Step 2: Verify no active legacy references remain**

Run:

```bash
rg -n "ProjectScreener|RoleScreener|DecisionReviewer|ApplicationService|DecisionBucket|ScreeningDecision|ReviewDecision|ApplicationDraft|project_decisions|project_reviews|record_decision|record_review|record_application|search_decisions|screening_counts|cover-letter|decisions command" src/backstage_agent tests README.md PROJECT_STATE.md ARCHITECTURE.md docs/module-guide.md
```

Expected: no matches outside inert SQL table/column names and historical
changelog/spec/plan text.

- [ ] **Step 3: Run the full suite and diff checks**

Run:

```bash
.venv/bin/python -m pytest
git diff --check main..HEAD
git status --short --branch
```

Expected: zero test failures, no diff whitespace errors, and only pre-existing
untracked files outside the committed removal.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md PROJECT_STATE.md CHANGELOG.md ARCHITECTURE.md docs/module-guide.md pyproject.toml
git commit -m "docs: describe scoring-only agent"
```

- [ ] **Step 5: Merge locally**

After the finishing-a-development-branch verification gate:

```bash
git switch main
git merge --ff-only codex/remove-legacy-system
.venv/bin/python -m pytest
```

Expected: fast-forward succeeds and the merged suite passes. Do not push, delete
feature branches, trigger launchd, or modify the active database.
