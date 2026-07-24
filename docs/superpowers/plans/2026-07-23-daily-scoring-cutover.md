# Daily Scoring Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scan` refresh and score daily candidates without invoking legacy screening, review, or application drafting, while preserving all legacy data and compatibility code.

**Architecture:** Keep email and Backstage-page ingestion in `BackstageAgent.scan()`, but replace the legacy decision pipeline with one call to the existing date-level candidate scoring service after all projects and roles are refreshed. Extend scan results and CLI summaries with safe scoring counters; keep the launchd shell entry point unchanged because it already calls `scan`.

**Tech Stack:** Python 3, dataclasses, argparse CLI, pytest, zsh launchd wrapper, SQLite through the existing `DecisionStore`.

## Global Constraints

- Preserve legacy screening, reviewer, application, storage, historical decision, CLI, and dashboard compatibility code.
- Do not invoke legacy project screening, project review, role screening, role review, or application drafting from `scan`.
- Preserve existing candidates by default; intentional replacement remains available only through `score-candidates --overwrite` and `rescore-candidates`.
- Preserve the one-day scheduled scan, 9:00-12:00 retry behavior, macOS notification behavior, and dashboard health check.
- Do not perform live IMAP, Backstage browser, model-provider, notification, or launchd verification.
- Use the existing candidate scoring fallbacks rather than dropping candidates on scoring-stage failures.

## File Structure

- Modify `src/backstage_agent/agent.py`: scoring-first scan orchestration and scan-result counters.
- Modify `tests/test_agent_review_gate.py`: replace legacy scan expectations with scoring-first orchestration and idempotency coverage.
- Modify `src/backstage_agent/cli.py`: scoring-oriented scan JSON and summary.
- Modify `tests/test_cli_summary.py`: scoring summary expectations and legacy-empty compatibility.
- Modify `tests/test_daily_scan_script.py`: describe and assert that the unchanged scheduled `scan` command is the scoring entry point.
- Modify `README.md`: default daily scoring workflow and retained manual overwrite commands.
- Modify `PROJECT_STATE.md`: current scoring-first capability and priorities.
- Modify `CHANGELOG.md`: user-visible daily workflow cutover.
- Modify `ARCHITECTURE.md`: scoring-first scan data flow and dormant legacy path.
- Modify `docs/module-guide.md`: new scan/scoring ownership.

---

### Task 1: Cut `scan` Over to Date-Level Candidate Scoring

**Files:**
- Modify: `tests/test_agent_review_gate.py`
- Modify: `src/backstage_agent/agent.py`

**Interfaces:**
- Consumes: `BackstageAgent.score_candidates_for_date(target_date: date, overwrite: bool = False) -> CandidateScoringResult`
- Produces: `ScanResult.candidates_scored: int`, `ScanResult.candidates_skipped_existing: int`, and `ScanResult.draft_suggestions: int`

- [ ] **Step 1: Replace the legacy scan tests with a failing scoring-first test**

Add candidate persistence helpers to `FakeStore`:

```python
def candidate_rescore_sources_for_date(self, target_date):
    return self.rescore_sources

def candidate_rows_for_date(self, target_date):
    return self.existing_candidate_rows

def clear_candidates_for_date(self, target_date):
    raise AssertionError("daily scan must not overwrite candidates")

def update_candidate_rank(self, candidate_id, rank_position, rank_score):
    return None
```

Initialize `rescore_sources = []` and `existing_candidate_rows = []`, then replace the legacy execution tests with:

```python
def test_scan_refreshes_and_scores_without_legacy_execution(monkeypatch):
    # Arrange one parsed project and role, with legacy collaborators replaced by
    # objects whose methods raise AssertionError if called.
    result = backstage_agent.scan(limit=1, days=1, target_date=date(2026, 7, 23))

    assert len(backstage_agent.store.refreshed_projects) == 1
    assert len(backstage_agent.store.refreshed_roles) == 1
    assert result.candidates_scored == 1
    assert result.candidates_skipped_existing == 0
    assert result.notices_seen == 1
    assert result.project_decisions == []
    assert result.project_reviews == []
    assert result.decisions == []
    assert result.reviews == []
    assert result.applications == []
```

The stored rescore source must contain the refreshed `ProjectNotice`, its role, and project id so the existing `generate_candidates()` path creates one role candidate.

- [ ] **Step 2: Add a failing preservation test**

```python
def test_scan_preserves_existing_candidate_scores(monkeypatch):
    backstage_agent.store.existing_candidate_rows = [existing_candidate_row]

    result = backstage_agent.scan(limit=1, days=1, target_date=date(2026, 7, 23))

    assert result.candidates_scored == 0
    assert result.candidates_skipped_existing == 1
    assert backstage_agent.store.candidates == []
```

Use an existing-row dictionary containing `candidate_type="role"`,
`role_key=<the role key>`, `project_key=<the project key>`, and the score fields
required by `_candidate_score_from_row()`.

- [ ] **Step 3: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/test_agent_review_gate.py -v
```

Expected: FAIL because `scan()` still calls legacy screeners and always reports zero candidates.

- [ ] **Step 4: Implement the minimal scoring-first orchestration**

Extend `ScanResult`:

```python
candidates_scored: int = 0
candidates_skipped_existing: int = 0
draft_suggestions: int = 0
```

In `scan()`, preserve fetch, parse, page-context enrichment, `upsert_project`,
`update_project_info`, and `upsert_role`. Remove legacy collaborator calls from
the method and count every refreshed page role in `notices_seen`. After all
messages are processed:

```python
scoring = self.score_candidates_for_date(seen_date, overwrite=False)
return ScanResult(
    messages_seen=len(messages),
    projects_seen=projects_seen,
    notices_seen=notices_seen,
    project_decisions=[],
    project_reviews=[],
    decisions=[],
    reviews=[],
    applications=[],
    candidates_scored=scoring.candidates_scored,
    candidates_skipped_existing=scoring.candidates_skipped_existing,
    draft_suggestions=sum(
        1
        for row in self.store.candidate_rows_for_date(seen_date.isoformat())
        if bool(row["draft_suggestion"])
    ),
)
```

Do not delete legacy imports, constructor wiring, helper functions, or classes;
they remain compatibility code for step 2.

- [ ] **Step 5: Run targeted orchestration and candidate tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_agent_review_gate.py tests/test_agent_candidate_scoring.py tests/test_candidate_storage.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit the orchestration cutover**

```bash
git add src/backstage_agent/agent.py tests/test_agent_review_gate.py
git commit -m "feat: make daily scan score candidates"
```

---

### Task 2: Make CLI and Scheduled-Run Reporting Scoring-First

**Files:**
- Modify: `tests/test_cli_summary.py`
- Modify: `tests/test_daily_scan_script.py`
- Modify: `src/backstage_agent/cli.py`

**Interfaces:**
- Consumes: scoring counters on `ScanResult`
- Produces: scan JSON key `candidates_skipped_existing` and a scoring-oriented `summary`

- [ ] **Step 1: Write failing CLI summary tests**

Replace legacy scan-summary assertions with:

```python
def test_scan_summary_reports_scoring_cutover():
    result = ScanResult(
        messages_seen=1,
        projects_seen=2,
        notices_seen=3,
        project_decisions=[],
        project_reviews=[],
        decisions=[],
        reviews=[],
        applications=[],
        candidates_scored=3,
        candidates_skipped_existing=2,
        draft_suggestions=1,
    )

    assert _scan_summary(result) == (
        "2 projects refreshed, 3 roles refreshed. "
        "Candidates: 3 scored, 2 existing skipped, 1 draft suggestion."
    )
```

Also assert the empty result says `0 scored` rather than falling back to legacy
decision counts.

- [ ] **Step 2: Update the scheduled-script contract test**

Rename `test_daily_scan_runs_selection_without_scoring_or_cli_notify` to
`test_daily_scan_uses_scoring_first_scan_without_second_command_or_cli_notify`.
Keep these assertions:

```python
assert "backstage_agent.cli scan --days 1 --limit 25" in script
assert "scan --days 1 --limit 25 --notify" not in script
assert "score-candidates" not in script
assert "rescore-candidates" not in script
```

This verifies there is one scheduled pipeline rather than a fragile two-command
sequence.

- [ ] **Step 3: Run the reporting tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_summary.py tests/test_daily_scan_script.py -v
```

Expected: CLI summary tests FAIL with legacy screening text; daily-script tests PASS because the shell command intentionally remains unchanged.

- [ ] **Step 4: Implement scoring-first CLI JSON and summary**

Add to `_scan()` JSON:

```python
"candidates_skipped_existing": result.candidates_skipped_existing,
```

Replace `_scan_summary()` with plural-safe scoring text:

```python
def _scan_summary(result) -> str:
    draft_label = "draft suggestion" if result.draft_suggestions == 1 else "draft suggestions"
    return (
        f"{result.projects_seen} projects refreshed, "
        f"{result.notices_seen} roles refreshed. "
        f"Candidates: {result.candidates_scored} scored, "
        f"{result.candidates_skipped_existing} existing skipped, "
        f"{result.draft_suggestions} {draft_label}."
    )
```

Leave `_bucket_summary()` and `_budget_warnings()` in place as legacy
compatibility helpers until step 2 removal.

- [ ] **Step 5: Run CLI, scheduling, and manual-scoring tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli_summary.py tests/test_cli_candidates.py tests/test_daily_scan_script.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit reporting changes**

```bash
git add src/backstage_agent/cli.py tests/test_cli_summary.py tests/test_daily_scan_script.py
git commit -m "feat: report daily candidate scoring"
```

---

### Task 3: Update Operational Documentation and Verify the Branch

**Files:**
- Modify: `README.md`
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/module-guide.md`

**Interfaces:**
- Consumes: completed scoring-first `scan` behavior
- Produces: an accurate operator and future-agent contract

- [ ] **Step 1: Update current-state documentation**

Make these exact behavioral statements consistent across the five files:

```text
The daily `scan` command refreshes projects and roles, then scores and ranks
candidates for that date. It does not run legacy screening, review, or
application drafting.

Existing candidate scores are preserved by default. Use
`score-candidates --date YYYY-MM-DD --overwrite` only for an intentional rebuild.

Legacy decisions, storage, dashboard views, and compatibility code remain
available pending the separately approved removal step.
```

In `PROJECT_STATE.md`, change the last-updated date to `2026-07-23`, replace the
manual-only scoring priority, and retain dry-run/live-submission limitations. In
`CHANGELOG.md`, add the cutover under `Changed`; do not claim the legacy system
was removed.

- [ ] **Step 2: Check documentation consistency**

Run:

```bash
rg -n "selection only|selection-only|manual mutual-selection|manual candidate|must not invoke|never invoked automatically|runs legacy" README.md PROJECT_STATE.md CHANGELOG.md ARCHITECTURE.md docs/module-guide.md
```

Expected: no statement claims that scheduled scoring is disabled or that
`scan` runs the legacy decision path. Historical changelog entries may remain.

- [ ] **Step 3: Run the full test suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: PASS with zero failures.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md PROJECT_STATE.md CHANGELOG.md ARCHITECTURE.md docs/module-guide.md
git commit -m "docs: document scoring-first daily workflow"
```

---

### Task 4: Merge the Verified Cutover to `main`

**Files:**
- No source-file changes expected.

**Interfaces:**
- Consumes: verified `codex/candidate-scoring` branch
- Produces: local `main` containing the scoring system and daily cutover

- [ ] **Step 1: Verify the worktree and branch state**

Run:

```bash
git status --short --branch
git rev-parse --git-dir
git rev-parse --git-common-dir
git merge-base HEAD main
```

Expected: current branch is `codex/candidate-scoring`; only the user's unrelated
untracked files remain; the branch has a valid merge base with `main`.

- [ ] **Step 2: Merge locally**

Because this is the normal repository rather than a disposable linked worktree:

```bash
git checkout main
git merge --ff-only codex/candidate-scoring
```

Expected: fast-forward succeeds. Do not pull, push, delete the feature branch, or
alter unrelated untracked files.

- [ ] **Step 3: Verify the merged result**

Run:

```bash
.venv/bin/python -m pytest
git status --short --branch
```

Expected: tests PASS with zero failures; `main` contains only the pre-existing
untracked files in working-tree status.

- [ ] **Step 4: Report operational limitations**

State explicitly that automated tests did not perform live IMAP access,
Backstage browser access, model-provider calls, macOS notification delivery, or
launchd execution. Do not trigger the scheduled job as part of the merge.
