# Selection-Only Morning Scan and Manual Candidate Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh and re-select repeated projects during the daily scan without running candidate scoring, and provide an explicit exact-date scoring command whose destructive replacement behavior requires `--overwrite`.

**Architecture:** Keep email ingestion and legacy selection in `BackstageAgent.scan()`, but replace early duplicate skips with storage upserts that refresh stable project and role identities. Move candidate generation/scoring behind one shared `score_candidates_for_date()` service returning structured counts; the new `score-candidates` CLI uses safe mode by default, while `--overwrite` and the existing `rescore-candidates` alias invoke replacement mode.

**Tech Stack:** Python 3, argparse, dataclasses, SQLite, pytest, zsh/launchd.

## Global Constraints

- Keep the scheduled command `scan --days 1 --limit 25 --notify` and its one-day default.
- The scheduled scan must not call feature extraction, requirement matching, candidate scoring, ranking, or candidate persistence.
- Repeated projects and roles must use the newest digest/page data and stable existing identities.
- Safe manual scoring must preserve existing candidate score payloads and candidate feedback.
- Candidate clearing is allowed only with `score-candidates --overwrite` or the compatibility `rescore-candidates` command.
- Preserve selection buckets, reviewer semantics, application blockers, dry-run/live-submission safety, and dashboard status semantics.
- Do not modify unrelated untracked files.

---

## File Structure

- `src/backstage_agent/storage.py`: own stable project/role refresh operations, last-seen scan dates, date-scoped candidate lookup, and feedback-safe overwrite cleanup.
- `src/backstage_agent/agent.py`: orchestrate selection-only scans and the shared manual scoring service.
- `src/backstage_agent/cli.py`: expose `score-candidates --date [--overwrite]`, retain the overwrite alias, and report structured counts.
- `tests/test_candidate_storage.py`: prove refresh identity, exact-date sources, candidate identity lookup, and feedback-safe clearing.
- `tests/test_agent_review_gate.py`: prove repeated inputs are refreshed and re-selected while scan does not score.
- `tests/test_agent_candidate_scoring.py`: move scan-scoring expectations to explicit manual scoring and prove safe/overwrite modes.
- `tests/test_cli_candidates.py`: prove CLI mode routing and JSON counts.
- `tests/test_daily_scan_script.py`: lock the scheduled script to selection-only `scan` behavior.
- `PROJECT_STATE.md`, `CHANGELOG.md`, `README.md`, `docs/module-guide.md`, `ARCHITECTURE.md`: document the new workflow and system boundary.

---

### Task 1: Refresh Stored Projects and Roles Safely

**Files:**
- Modify: `src/backstage_agent/storage.py`
- Test: `tests/test_candidate_storage.py`

**Interfaces:**
- Produces: `DecisionStore.upsert_project(project: ProjectNotice, seen_date: date) -> int`
- Produces: `DecisionStore.upsert_role(project_id: int, notice: CastingNotice) -> int`
- Produces: `DecisionStore.candidate_rows_for_date(target_date: str) -> list[sqlite3.Row]` for safe-mode identity checks and combined reranking.
- Produces: `DecisionStore.update_candidate_rank(candidate_id: int, rank_score: int, rank_position: int) -> None`, which updates rank columns without replacing score/audit JSON.
- Changes: `DecisionStore.clear_candidates_for_date(target_date: str) -> int` keeps the existing feedback-row behavior and has an explicit regression test.
- Consumes later: `BackstageAgent.scan()` and `BackstageAgent.score_candidates_for_date()`.

- [ ] **Step 1: Write failing storage refresh tests**

Add tests that insert old records, upsert newer objects with the same keys, and assert stable IDs plus newest mutable data:

```python
def test_upsert_project_and_role_refresh_newest_data_without_new_ids(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    old_project = ProjectNotice(
        source_message_id="old-message",
        title="Repeated Project",
        project_url="https://example.com/project",
        description="Old description",
        raw_text="Old raw text",
        project_date=date(2026, 7, 10),
        project_key="repeated-project",
    )
    project_id = store.upsert_project(old_project, seen_date=date(2026, 7, 10))
    old_role = casting_notice_factory(
        source_message_id="old-message",
        project_key="repeated-project",
        role_key="repeated-role",
        compensation="$50",
        description="Old role data",
    )
    role_id = store.upsert_role(project_id, old_role)

    refreshed_project = replace(
        old_project,
        source_message_id="new-message",
        description="Newest description",
        raw_text="Newest raw text",
    )
    refreshed_role = replace(
        old_role,
        source_message_id="new-message",
        compensation="$500",
        description="Newest role data",
    )

    assert store.upsert_project(refreshed_project, seen_date=date(2026, 7, 15)) == project_id
    assert store.upsert_role(project_id, refreshed_role) == role_id
    sources = store.candidate_rescore_sources_for_date("2026-07-15")
    assert sources[0][0].description == "Newest description"
    assert sources[0][1][0][1].compensation == "$500"
```

Add `from dataclasses import replace` to the test imports.

- [ ] **Step 2: Run the refresh test and verify RED**

Run:

```sh
.venv/bin/python -m pytest tests/test_candidate_storage.py::test_upsert_project_and_role_refresh_newest_data_without_new_ids -v
```

Expected: FAIL because `upsert_project` and `upsert_role` do not exist.

- [ ] **Step 3: Implement schema migration and upserts**

Extend the projects schema/migration with `last_seen_date TEXT`, and implement upserts using existing key builders. The project update must replace newest digest fields while retaining existing non-empty page fields when the new value is absent:

```python
def upsert_project(self, project: ProjectNotice, seen_date: date) -> int:
    project_key = project.project_key or build_project_key(
        project.title, project.project_url, project.project_date
    )
    with self._connect() as conn:
        row = conn.execute(
            "SELECT id FROM projects WHERE project_key = ? ORDER BY id DESC LIMIT 1",
            (project_key,),
        ).fetchone()
        if row is None:
            cursor = conn.execute(
                """INSERT INTO projects (
                     source_message_id, title, project_url, description, raw_text,
                     project_date, project_key, shooting_locations, shooting_dates,
                     last_seen_date
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project.source_message_id, project.title, project.project_url,
                    project.description, project.raw_text,
                    project.project_date.isoformat() if project.project_date else None,
                    project_key, project.shooting_locations, project.shooting_dates,
                    seen_date.isoformat(),
                ),
            )
            return int(cursor.lastrowid)
        project_id = int(row[0])
        conn.execute(
            """UPDATE projects
               SET source_message_id = ?, title = ?, project_url = ?,
                   description = ?, raw_text = ?, project_date = ?,
                   shooting_locations = COALESCE(?, shooting_locations),
                   shooting_dates = COALESCE(?, shooting_dates), last_seen_date = ?
               WHERE id = ?""",
            (
                project.source_message_id, project.title, project.project_url,
                project.description, project.raw_text,
                project.project_date.isoformat() if project.project_date else None,
                project.shooting_locations, project.shooting_dates,
                seen_date.isoformat(), project_id,
            ),
        )
        return project_id
```

Implement `upsert_role()` with the same stable `role_key` lookup and an UPDATE of all mutable role/notice fields. Update `candidate_rescore_sources_for_date()` and `clear_candidates_for_date()` date predicates to use `COALESCE(last_seen_date, project_date, created_at)`.

- [ ] **Step 4: Run the refresh test and verify GREEN**

Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Write failing candidate identity and feedback-preservation tests**

```python
def test_candidate_rows_for_date_and_clear_preserve_feedback(tmp_path, casting_notice_factory):
    store = DecisionStore(tmp_path / "db.sqlite3")
    project_id = store.upsert_project(
        ProjectNotice(
            source_message_id="m1", title="Stored Project",
            project_url="https://example.com/project", description="Description",
            raw_text="Raw", project_date=date(2026, 7, 15),
            project_key="stored-project",
        ),
        seen_date=date(2026, 7, 15),
    )
    role = casting_notice_factory(project_key="stored-project", role_key="stored-role")
    role_id = store.upsert_role(project_id, role)
    candidate_id = store.record_candidate(
        CandidateInput.role_candidate(
            project_id=project_id, role_id=role_id,
            project_key="stored-project", role_key="stored-role",
            title=role.title, notice=role,
        ),
        _features(), [_match()], _score(),
    )
    store.record_candidate_feedback(
        HumanFeedback(
            candidate_id=candidate_id, agent_score=86, human_score=60,
            affected_components=["identity_match"],
            failure_modes=["overweighted_signal"], free_text_reason="Keep me",
        )
    )

    rows = store.candidate_rows_for_date("2026-07-15")
    assert [(row["candidate_type"], row["role_key"]) for row in rows] == [
        ("role", "stored-role")
    ]
    assert store.clear_candidates_for_date("2026-07-15") == 1
    with store._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_feedback").fetchone()[0] == 1
        assert conn.execute("SELECT candidate_id FROM candidate_feedback").fetchone()[0] == candidate_id
```

Use the stored `candidate_type` value from `CandidateType.ROLE.value` in the final assertion if the enum value differs from `"role"`.

- [ ] **Step 6: Run the identity test and verify RED**

Run:

```sh
.venv/bin/python -m pytest tests/test_candidate_storage.py::test_candidate_rows_for_date_and_clear_preserve_feedback -v
```

Expected: FAIL because `candidate_rows_for_date` is missing.

- [ ] **Step 7: Implement date-scoped candidate rows and rank updates**

Return full candidate rows for projects whose effective date matches the target. Implement `update_candidate_rank()` to update only `rank_score`, `rank_position`, and `updated_at`; do not rewrite `score_json`, `features_json`, or `requirement_match_json`. Keep `clear_candidates_for_date()` scoped to the same effective-date predicate and verify that its current SQLite behavior retains `candidate_feedback` audit rows.

- [ ] **Step 8: Run storage tests**

Run:

```sh
.venv/bin/python -m pytest tests/test_candidate_storage.py -v
```

Expected: all tests PASS.

- [ ] **Step 9: Commit Task 1**

```sh
git add src/backstage_agent/storage.py tests/test_candidate_storage.py
git commit -m "feat: refresh repeated casting data safely"
```

---

### Task 2: Make Scan Selection-Only and Reprocess Repeated Data

**Files:**
- Modify: `src/backstage_agent/agent.py`
- Modify: `tests/test_agent_review_gate.py`
- Modify: `tests/test_agent_candidate_scoring.py`
- Create: `tests/test_daily_scan_script.py`

**Interfaces:**
- Consumes: `DecisionStore.upsert_project()` and `DecisionStore.upsert_role()` from Task 1.
- Changes: `BackstageAgent.scan(limit: int, days: int = 1, target_date: date | None = None) -> ScanResult` performs selection only.
- Preserves: `ScanResult.candidates_scored == 0` and `draft_suggestions == 0` for output compatibility.

- [ ] **Step 1: Write failing repeated-selection and no-scoring tests**

Adapt `FakeStore` to expose `upsert_project()`/`upsert_role()` and record refreshed objects. Add:

```python
def test_scan_refreshes_repeated_project_and_runs_selection_without_scoring(monkeypatch):
    notice = _role_notice_with_keys("repeated-project", "repeated-role")
    project = ProjectNotice(
        source_message_id="new-message", title="Repeated Project",
        project_url="https://example.com/project", description="Newest digest",
        raw_text="Newest digest", project_key="repeated-project",
    )
    agent = _agent_with(notice)
    agent.feature_extractor = SimpleNamespace(
        extract=lambda candidate: (_ for _ in ()).throw(AssertionError("scoring ran"))
    )
    monkeypatch.setattr("backstage_agent.agent.parse_project_notices", lambda message: [project])
    monkeypatch.setattr("backstage_agent.agent.parse_project_page_roles", lambda project, html: [notice])
    agent.project_pages.fetch_html = lambda url: "<html></html>"

    result = agent.scan(limit=1, target_date=date(2026, 7, 15))

    assert len(result.project_decisions) == 1
    assert len(result.decisions) == 1
    assert result.candidates_scored == 0
    assert result.draft_suggestions == 0
    assert agent.store.candidates == []
    assert agent.store.refreshed_projects[0].description == "Newest digest"
```

The fake store should simulate an already-known identity but allow the upsert and latest decision recording, proving that the old `project_notice_exists()`/`decision_exists()` early exits are no longer controlling scan behavior.

- [ ] **Step 2: Run the orchestration test and verify RED**

Run:

```sh
.venv/bin/python -m pytest tests/test_agent_review_gate.py::test_scan_refreshes_repeated_project_and_runs_selection_without_scoring -v
```

Expected: FAIL because scan still invokes candidate scoring or skips existing identities.

- [ ] **Step 3: Remove scoring and duplicate skips from scan**

In `scan()`:

```python
seen_date = target_date or datetime.now().astimezone().date()
for project in projects:
    project_id = self.store.upsert_project(project, seen_date=seen_date)
    html = self.project_pages.fetch_html(project.project_url)
    # retain existing page-context enrichment
    # run project selection and review for every parsed project
    stored_roles = []
    for role in page_roles:
        role_id = self.store.upsert_role(project_id, role)
        stored_roles.append((role_id, role))
        if allow_legacy_role_flow:
            notices.append(role)
```

Remove candidate generation, scoring, ranking, and persistence from `scan()`. Return zero compatibility counts. Remove unused scan-path imports only if they are no longer used by the manual scoring methods.

- [ ] **Step 4: Run targeted agent tests and verify GREEN**

Run:

```sh
.venv/bin/python -m pytest tests/test_agent_review_gate.py tests/test_agent_candidate_scoring.py -v
```

Expected: selection tests PASS; old tests that expect scan-time scoring must be moved to Task 3 rather than weakened.

- [ ] **Step 5: Add the daily-script contract test**

```python
from pathlib import Path


def test_daily_scan_runs_selection_without_scoring_command():
    script = Path("scripts/daily_scan.sh").read_text(encoding="utf-8")
    assert "backstage_agent.cli scan --days 1 --limit 25 --notify" in script
    assert "score-candidates" not in script
    assert "rescore-candidates" not in script
```

- [ ] **Step 6: Run the script test**

Run:

```sh
.venv/bin/python -m pytest tests/test_daily_scan_script.py -v
```

Expected: PASS, confirming the existing script already has the desired command boundary.

- [ ] **Step 7: Commit Task 2**

```sh
git add src/backstage_agent/agent.py tests/test_agent_review_gate.py tests/test_agent_candidate_scoring.py tests/test_daily_scan_script.py
git commit -m "fix: make morning scan selection only"
```

---

### Task 3: Add Safe Manual Scoring and Explicit Overwrite

**Files:**
- Modify: `src/backstage_agent/agent.py`
- Modify: `src/backstage_agent/cli.py`
- Modify: `tests/test_agent_candidate_scoring.py`
- Modify: `tests/test_cli_candidates.py`

**Interfaces:**
- Produces: `CandidateScoringResult(date: date, overwrite: bool, candidates_scored: int, candidates_skipped_existing: int, candidates_deleted: int)` dataclass.
- Produces: `BackstageAgent.score_candidates_for_date(target_date: date, overwrite: bool = False) -> CandidateScoringResult`.
- Preserves: `BackstageAgent.rescore_candidates_for_date(target_date: date) -> int` as a thin compatibility wrapper returning the overwrite result's `candidates_scored`.
- Produces CLI: `score-candidates --date YYYY-MM-DD [--overwrite]`.

- [ ] **Step 1: Write failing safe and overwrite service tests**

Convert the former scan-scoring fixtures to stored project/role sources and add:

```python
def test_score_candidates_for_date_skips_existing_without_overwrite(agent_with_stored_sources):
    agent = agent_with_stored_sources(existing_role_keys={"existing-role"})

    result = agent.score_candidates_for_date(date(2026, 7, 15))

    assert result.overwrite is False
    assert result.candidates_scored == 1
    assert result.candidates_skipped_existing == 1
    assert result.candidates_deleted == 0
    assert agent.store.clear_calls == []
    assert agent.feature_extractor.extracted_role_keys == ["new-role"]
    assert agent.store.existing_score_json_unchanged is True
    assert agent.store.updated_rank_ids == [agent.store.existing_candidate_id]


def test_score_candidates_for_date_overwrite_rebuilds_all(agent_with_stored_sources):
    agent = agent_with_stored_sources(existing_role_keys={"existing-role"})

    result = agent.score_candidates_for_date(date(2026, 7, 15), overwrite=True)

    assert result.overwrite is True
    assert result.candidates_scored == 2
    assert result.candidates_skipped_existing == 0
    assert result.candidates_deleted == 1
    assert agent.feature_extractor.extracted_role_keys == ["existing-role", "new-role"]
```

- [ ] **Step 2: Run service tests and verify RED**

Run:

```sh
.venv/bin/python -m pytest tests/test_agent_candidate_scoring.py -v
```

Expected: FAIL because `score_candidates_for_date` and `CandidateScoringResult` do not exist.

- [ ] **Step 3: Implement the shared scoring service**

```python
@dataclass(frozen=True)
class CandidateScoringResult:
    date: date
    overwrite: bool
    candidates_scored: int
    candidates_skipped_existing: int
    candidates_deleted: int


def score_candidates_for_date(
    self,
    target_date: date,
    overwrite: bool = False,
) -> CandidateScoringResult:
    target = target_date.isoformat()
    deleted = self.store.clear_candidates_for_date(target) if overwrite else 0
    existing_rows = [] if overwrite else self.store.candidate_rows_for_date(target)
    existing = {_candidate_row_identity(row) for row in existing_rows}
    records = []
    skipped = 0
    for project, stored_roles, project_id in self.store.candidate_rescore_sources_for_date(target):
        for candidate in generate_candidates(project_id, project, stored_roles):
            identity = _candidate_identity(candidate)
            if identity in existing:
                skipped += 1
                continue
            features, matches, score = self._score_candidate_with_fallback(candidate)
            records.append((candidate, features, matches, score))
    ranked = self._rank_new_and_existing_candidates(records, existing_rows)
    for candidate, features, matches, score in ranked.new_records:
        self.store.record_candidate(candidate, features, matches, score)
    for candidate_id, rank_score, rank_position in ranked.existing_rank_updates:
        self.store.update_candidate_rank(candidate_id, rank_score, rank_position)
    return CandidateScoringResult(target_date, overwrite, len(ranked.new_records), skipped, deleted)
```

Implement `_candidate_identity()` and `_candidate_row_identity()` using the exact same `(candidate_type.value, role_key or project_key)` shape. Implement `_rank_new_and_existing_candidates()` by reconstructing the minimal `CandidateScore` values needed by `rank_candidates()` from existing row columns, tagging existing rows and new records with stable internal identities, then splitting the ranked output into new records and existing rank-column updates. This provides a single combined date ranking while leaving existing feature, match, and score JSON audit payloads unchanged. Keep `rescore_candidates_for_date()` as `return self.score_candidates_for_date(target_date, overwrite=True).candidates_scored`.

- [ ] **Step 4: Run service tests and verify GREEN**

Run the Step 2 command. Expected: all candidate scoring tests PASS.

- [ ] **Step 5: Write failing CLI routing and JSON tests**

```python
def test_score_candidates_json_reports_safe_counts(monkeypatch):
    class FakeAgent:
        def __init__(self, settings):
            pass

        def score_candidates_for_date(self, target_date, overwrite=False):
            return CandidateScoringResult(target_date, overwrite, 2, 3, 0)

    monkeypatch.setattr("backstage_agent.cli.BackstageAgent", FakeAgent)
    output = json.loads(
        _score_candidates_for_date("2026-07-15", overwrite=False, settings=object())
    )
    assert output == {
        "date": "2026-07-15", "overwrite": False,
        "candidates_scored": 2, "candidates_skipped_existing": 3,
        "candidates_deleted": 0,
    }


def test_rescore_alias_uses_overwrite(monkeypatch):
    class FakeAgent:
        def __init__(self, settings):
            pass

        def score_candidates_for_date(self, target_date, overwrite=False):
            assert overwrite is True
            return CandidateScoringResult(target_date, True, 4, 0, 2)

    monkeypatch.setattr("backstage_agent.cli.BackstageAgent", FakeAgent)
    output = json.loads(_rescore_candidates_for_date("2026-07-15", settings=object()))
    assert output["overwrite"] is True
    assert output["candidates_deleted"] == 2
```

- [ ] **Step 6: Run CLI tests and verify RED**

Run:

```sh
.venv/bin/python -m pytest tests/test_cli_candidates.py -v
```

Expected: FAIL because the new parser/helper and expanded result JSON are missing.

- [ ] **Step 7: Implement CLI parser and compatibility alias**

Add:

```python
score_parser = subparsers.add_parser(
    "score-candidates",
    help="Score stored candidates for one date without replacing existing scores",
)
score_parser.add_argument("--date", required=True, help="Project date, formatted YYYY-MM-DD")
score_parser.add_argument(
    "--overwrite", action="store_true",
    help="Delete and rebuild existing candidate scores for the date",
)
```

Dispatch it to `_score_candidates_for_date(args.date, args.overwrite)`. Serialize all five `CandidateScoringResult` fields. Make `_rescore_candidates_for_date()` call the same helper with `overwrite=True`.

- [ ] **Step 8: Run CLI and agent tests**

Run:

```sh
.venv/bin/python -m pytest tests/test_cli_candidates.py tests/test_agent_candidate_scoring.py -v
```

Expected: all tests PASS.

- [ ] **Step 9: Verify help text without external actions**

Run:

```sh
.venv/bin/python -m backstage_agent.cli score-candidates --help
```

Expected: exit 0 and output includes `--date` and `--overwrite`.

- [ ] **Step 10: Commit Task 3**

```sh
git add src/backstage_agent/agent.py src/backstage_agent/cli.py tests/test_agent_candidate_scoring.py tests/test_cli_candidates.py
git commit -m "feat: add manual candidate scoring command"
```

---

### Task 4: Update Documentation and Verify the Complete Workflow

**Files:**
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `docs/module-guide.md`
- Modify: `ARCHITECTURE.md`

**Interfaces:**
- Documents: selection-only scheduled scan, newest-data refresh, safe scoring, explicit overwrite, and compatibility alias.
- Verifies: all behavior implemented by Tasks 1-3.

- [ ] **Step 1: Update user and maintainer documentation**

Add the exact commands to README:

```sh
# Daily selection only
.venv/bin/python -m backstage_agent.cli scan --days 1 --limit 25 --notify

# Score only candidates that do not already have scores
.venv/bin/python -m backstage_agent.cli score-candidates --date 2026-07-15

# Delete and rebuild that date's candidate scores
.venv/bin/python -m backstage_agent.cli score-candidates --date 2026-07-15 --overwrite
```

State in `PROJECT_STATE.md` that daily scans refresh repeated projects from newest data and do not run scoring. Add a concise `CHANGELOG.md` entry. Update `docs/module-guide.md` candidate-scoring entry points. Update `ARCHITECTURE.md` flow from a combined scan to two explicit flows: `scan -> selection` and `score-candidates -> candidate scoring`.

- [ ] **Step 2: Run documentation consistency searches**

Run:

```sh
rg -n "score-candidates|rescore-candidates|selection.only|candidate scor" README.md PROJECT_STATE.md CHANGELOG.md ARCHITECTURE.md docs/module-guide.md
```

Expected: each command and boundary is described consistently; no text claims the daily scan automatically scores candidates.

- [ ] **Step 3: Run targeted regression tests**

Run:

```sh
.venv/bin/python -m pytest tests/test_candidate_storage.py tests/test_agent_review_gate.py tests/test_agent_candidate_scoring.py tests/test_cli_candidates.py tests/test_cli_summary.py tests/test_daily_scan_script.py -v
```

Expected: all targeted tests PASS with zero failures.

- [ ] **Step 4: Run the full suite**

Run:

```sh
.venv/bin/python -m pytest -q
```

Expected: all tests PASS with zero failures.

- [ ] **Step 5: Run static and shell checks**

Run:

```sh
.venv/bin/python -m compileall -q src tests
zsh -n scripts/daily_scan.sh
plutil -lint launchd/com.sarahtxy.backstage-agent.daily.plist
git diff --check
```

Expected: every command exits 0; plist output ends with `OK`.

- [ ] **Step 6: Inspect final scope**

Run:

```sh
git status --short
git diff --stat HEAD
```

Expected: only the planned code, tests, and documentation are changed; the pre-existing untracked cover-letter plan/spec remain untouched.

- [ ] **Step 7: Commit Task 4**

```sh
git add PROJECT_STATE.md CHANGELOG.md README.md docs/module-guide.md ARCHITECTURE.md
git commit -m "docs: separate daily selection from manual scoring"
```

- [ ] **Step 8: Report live-verification limits**

Do not run the live morning scan, IMAP fetch, model-backed scoring, Backstage browser access, notification delivery, or launchd reload as part of local verification. Report these as unverified external behaviors; the user can invoke the manual scoring command for a chosen date after reviewing the local test results.
