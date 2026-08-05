# Bootstrap Calibration Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build aggressive, auditable bootstrap calibration that uses one latest active label per stable candidate/component, recalculates residuals against the current scoring version, and records equivalent proposals only once.

**Architecture:** Add an append-only normalized calibration-evidence table beside the existing feedback and dashboard-correction tables. A focused calibration service reads active evidence, rejects incompatible scoring versions, calculates residuals from current stored scores, applies auditable age-based decay, bounds bootstrap proposals to plus or minus five points, and persists proposal/evidence links idempotently. Existing feedback and correction interfaces remain compatible and feed the normalized evidence ledger transactionally.

**Tech Stack:** Python 3, dataclasses, SQLite/JSON1, argparse, pytest

## Global Constraints

- Preserve every historical feedback submission; never delete historical evidence.
- Use stable `candidate_type + project_key + role_key + component_name` identity, not volatile candidate row IDs.
- Only the latest submission for a stable candidate/component is active.
- Count distinct candidates, not repeated submissions.
- Weight active cross-candidate evidence by age: 0-30 days `1.00`, 31-90 days `0.70`, 91-180 days `0.40`, and older than 180 days `0.20`.
- When a component has at least five active labels from the last 30 days, evidence older than 90 days is stability-only with proposal weight `0.00`.
- Superseded same-candidate/component evidence always has proposal weight `0.00`.
- Bootstrap stage covers 1-5 active candidates and bounds proposed changes to plus or minus 5 points.
- Do not automatically modify `scoring_rules.json` or accept calibration proposals.
- Repeating calibration with unchanged scoring version and evidence must not insert a duplicate proposal.
- Existing dashboard correction display and overwrite behavior must remain unchanged.
- Initial implementation delivers bootstrap behavior only; learning and mature stages remain documented future work.

---

## File Structure

- Modify `src/backstage_agent/candidate_models.py`: define normalized evidence, evaluated residual, and expanded proposal result dataclasses.
- Modify `src/backstage_agent/storage.py`: create/migrate the evidence ledger, append/supersede active labels, query current evidence, and persist proposal evidence idempotently.
- Modify `src/backstage_agent/calibration.py`: evaluate current-version residuals, apply historical weight decay, and build bounded bootstrap proposals.
- Modify `src/backstage_agent/cli.py`: record normalized CLI evidence and expose idempotent calibration output.
- Modify `src/backstage_agent/ui.py`: append normalized evidence whenever a dashboard correction is saved while retaining the existing correction overlay.
- Modify `tests/test_candidate_models.py`: cover model defaults and validation-oriented properties.
- Modify `tests/test_candidate_storage.py`: cover supersession, stable identities, migration, history, and idempotent proposal persistence.
- Modify `tests/test_calibration.py`: cover residual evaluation, age-weight boundaries, recent-evidence displacement, and bootstrap adjustment bounds.
- Modify `tests/test_cli_candidates.py`: cover command output and repeat-run behavior.
- Modify `tests/test_ui_candidates.py`: prove correction saves also append calibration evidence.
- Modify `README.md`, `PROJECT_STATE.md`, and `CHANGELOG.md`: document current bootstrap behavior and future maturity stages.

---

### Task 1: Normalized Calibration Evidence Ledger

**Files:**
- Modify: `src/backstage_agent/candidate_models.py`
- Modify: `src/backstage_agent/storage.py`
- Test: `tests/test_candidate_models.py`
- Test: `tests/test_candidate_storage.py`

**Interfaces:**
- Consumes: existing candidate rows with `candidate_type`, `project_key`, `role_key`, `score_json`, and `scoring_version`.
- Produces: `CalibrationEvidence`, `DecisionStore.record_calibration_evidence(evidence) -> int`, `DecisionStore.active_calibration_evidence() -> list[sqlite3.Row]`, and `DecisionStore.calibration_evidence_history(...) -> list[sqlite3.Row]`.

- [ ] **Step 1: Write failing model and storage tests**

Add imports and tests equivalent to:

```python
from backstage_agent.candidate_models import CalibrationEvidence


def _evidence(candidate_id: int, human_target: int = 8) -> CalibrationEvidence:
    return CalibrationEvidence(
        source_type="dashboard_correction",
        source_id=str(candidate_id),
        candidate_type="role",
        project_key="project",
        role_key="role",
        candidate_id_at_submission=candidate_id,
        component_name="role_value",
        failure_mode="subscore_override",
        target_kind="component",
        human_target=human_target,
        submitted_agent_score=15,
        scoring_version="test-v1",
    )


def test_latest_calibration_evidence_supersedes_same_role_component(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    first_id = store.record_calibration_evidence(_evidence(10, 8))
    second_id = store.record_calibration_evidence(_evidence(11, 12))

    active = store.active_calibration_evidence()
    history = store.calibration_evidence_history("role", "project", "role", "role_value")

    assert [row["id"] for row in active] == [second_id]
    assert [row["id"] for row in history] == [second_id, first_id]
    assert history[1]["superseded_at"] is not None


def test_calibration_evidence_keeps_different_metrics_active(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    store.record_calibration_evidence(_evidence(10, 8))
    store.record_calibration_evidence(replace(_evidence(10, 4), component_name="logistics"))

    assert {row["component_name"] for row in store.active_calibration_evidence()} == {
        "role_value",
        "logistics",
    }


def test_calibration_identity_survives_candidate_rescore_id_change(tmp_path):
    store = DecisionStore(tmp_path / "db.sqlite3")
    first_id = store.record_calibration_evidence(_evidence(10, 8))
    second_id = store.record_calibration_evidence(_evidence(99, 9))

    assert second_id != first_id
    assert store.active_calibration_evidence()[0]["candidate_id_at_submission"] == 99
    assert len(store.calibration_evidence_history("role", "project", "role", "role_value")) == 2
```

Also assert `CalibrationEvidence.stable_key == ("role", "project", "role", "role_value")` in `tests/test_candidate_models.py`.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_candidate_models.py \
  tests/test_candidate_storage.py::test_latest_calibration_evidence_supersedes_same_role_component \
  tests/test_candidate_storage.py::test_calibration_evidence_keeps_different_metrics_active \
  tests/test_candidate_storage.py::test_calibration_identity_survives_candidate_rescore_id_change -v
```

Expected: FAIL because `CalibrationEvidence` and the ledger storage methods do not exist.

- [ ] **Step 3: Add the evidence model**

Add to `candidate_models.py`:

```python
@dataclass(frozen=True)
class CalibrationEvidence:
    source_type: str
    source_id: str
    candidate_type: str
    project_key: str
    role_key: str
    candidate_id_at_submission: int
    component_name: str
    failure_mode: str
    target_kind: str
    human_target: int
    submitted_agent_score: int
    scoring_version: str

    @property
    def stable_key(self) -> tuple[str, str, str, str]:
        return (
            self.candidate_type,
            self.project_key,
            self.role_key or "",
            self.component_name,
        )
```

- [ ] **Step 4: Add the ledger schema and migration-safe indexes**

In `_ensure_schema()`, add:

```sql
CREATE TABLE IF NOT EXISTS candidate_calibration_evidence (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  superseded_at TEXT,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  candidate_type TEXT NOT NULL,
  project_key TEXT NOT NULL,
  role_key TEXT NOT NULL DEFAULT '',
  candidate_id_at_submission INTEGER NOT NULL,
  component_name TEXT NOT NULL,
  failure_mode TEXT NOT NULL,
  target_kind TEXT NOT NULL CHECK(target_kind IN ('component', 'overall')),
  human_target INTEGER NOT NULL,
  submitted_agent_score INTEGER NOT NULL,
  scoring_version TEXT NOT NULL,
  UNIQUE(source_type, source_id, component_name)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_calibration_evidence_active
ON candidate_calibration_evidence(candidate_type, project_key, role_key, component_name)
WHERE superseded_at IS NULL;
```

Do not migrate legacy rows in this step; Task 2 routes both current write paths into the ledger and performs the one-time backfill.

- [ ] **Step 5: Implement transactional supersession and queries**

Add methods with these exact signatures:

```python
def record_calibration_evidence(self, evidence: CalibrationEvidence) -> int:
    role_key = evidence.role_key or ""
    with self._connect() as conn:
        existing = conn.execute(
            """
            SELECT id FROM candidate_calibration_evidence
            WHERE source_type = ? AND source_id = ? AND component_name = ?
            """,
            (evidence.source_type, evidence.source_id, evidence.component_name),
        ).fetchone()
        if existing:
            return int(existing[0])
        conn.execute(
            """
            UPDATE candidate_calibration_evidence
            SET superseded_at = CURRENT_TIMESTAMP
            WHERE candidate_type = ? AND project_key = ? AND role_key = ?
              AND component_name = ? AND superseded_at IS NULL
            """,
            (*evidence.stable_key[:2], role_key, evidence.component_name),
        )
        cursor = conn.execute(
            """
            INSERT INTO candidate_calibration_evidence (
              source_type, source_id, candidate_type, project_key, role_key,
              candidate_id_at_submission, component_name, failure_mode,
              target_kind, human_target, submitted_agent_score, scoring_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.source_type, evidence.source_id, evidence.candidate_type,
                evidence.project_key, role_key, evidence.candidate_id_at_submission,
                evidence.component_name, evidence.failure_mode, evidence.target_kind,
                evidence.human_target, evidence.submitted_agent_score,
                evidence.scoring_version,
            ),
        )
        return int(cursor.lastrowid)

def active_calibration_evidence(self) -> list[sqlite3.Row]:
    with self._connect() as conn:
        conn.row_factory = sqlite3.Row
        return list(conn.execute(
            "SELECT * FROM candidate_calibration_evidence WHERE superseded_at IS NULL ORDER BY id"
        ))

def calibration_evidence_history(
    self, candidate_type: str, project_key: str, role_key: str, component_name: str
) -> list[sqlite3.Row]:
    with self._connect() as conn:
        conn.row_factory = sqlite3.Row
        return list(conn.execute(
            """
            SELECT * FROM candidate_calibration_evidence
            WHERE candidate_type = ? AND project_key = ? AND role_key = ?
              AND component_name = ? ORDER BY id DESC
            """,
            (candidate_type, project_key, role_key or "", component_name),
        ))
```

- [ ] **Step 6: Run tests to verify GREEN**

Run the command from Step 2. Expected: PASS.

- [ ] **Step 7: Commit the ledger**

```bash
git add src/backstage_agent/candidate_models.py src/backstage_agent/storage.py \
  tests/test_candidate_models.py tests/test_candidate_storage.py
git commit -m "feat: add calibration evidence ledger"
```

---

### Task 2: Route Feedback Sources and Backfill Existing Data

**Files:**
- Modify: `src/backstage_agent/storage.py`
- Modify: `src/backstage_agent/cli.py`
- Modify: `src/backstage_agent/ui.py`
- Test: `tests/test_candidate_storage.py`
- Test: `tests/test_cli_candidates.py`
- Test: `tests/test_ui_candidates.py`

**Interfaces:**
- Consumes: `DecisionStore.record_calibration_evidence(CalibrationEvidence) -> int` from Task 1.
- Produces: new writes from CLI feedback and dashboard corrections in the normalized ledger; `_backfill_calibration_evidence(conn) -> None` for existing databases.

- [ ] **Step 1: Write failing routing and migration tests**

Add tests proving:

```python
def test_record_candidate_feedback_expands_components_into_active_evidence(...):
    feedback_id = store.record_candidate_feedback(HumanFeedback(
        candidate_id=candidate_id,
        agent_score=80,
        human_score=60,
        affected_components=["role_value", "logistics"],
        failure_modes=["overweighted_signal"],
        free_text_reason="Both are too high.",
    ))
    evidence = store.active_calibration_evidence()
    assert {(row["component_name"], row["source_id"]) for row in evidence} == {
        ("role_value", feedback_id),
        ("logistics", feedback_id),
    }
    assert all(row["target_kind"] == "overall" for row in evidence)


def test_upsert_candidate_correction_appends_evidence_and_latest_wins(...):
    first_correction_id = store.upsert_candidate_correction(first)
    store.upsert_candidate_correction(second)
    active = store.active_calibration_evidence()
    assert len(active) == 1
    assert active[0]["human_target"] == second.corrected_component_score
    assert len(store.calibration_evidence_history("role", "project", "role", "role_value")) == 2
```

Because the existing correction row is updated in place, use a monotonically unique evidence source ID. Add `revision INTEGER NOT NULL DEFAULT 1` to `candidate_score_corrections`, increment it in the conflict update, and encode the Task 1 text `source_id` as `f"{correction_id}:{revision}"`.

Add a migration test that creates a database with the old tables, inserts two feedback rows for the same stable role/component, initializes `DecisionStore`, and asserts both appear in history while only the newer row is active.

- [ ] **Step 2: Run tests to verify RED**

```bash
.venv/bin/python -m pytest \
  tests/test_candidate_storage.py::test_record_candidate_feedback_expands_components_into_active_evidence \
  tests/test_candidate_storage.py::test_upsert_candidate_correction_appends_evidence_and_latest_wins \
  tests/test_candidate_storage.py::test_existing_feedback_is_backfilled_with_latest_active -v
```

Expected: FAIL because current write paths do not create normalized evidence and no backfill exists.

- [ ] **Step 3: Make legacy feedback insertion and evidence insertion atomic**

Refactor `record_candidate_feedback()` to load the candidate stable identity, insert the legacy row, and call a private connection-scoped helper once per affected component. Pair failure modes by matching index when lengths match; otherwise use the first failure mode for every component. Store `target_kind="overall"`, `human_target=feedback.human_score`, and `submitted_agent_score=feedback.agent_score`.

The helper signature is:

```python
def _record_calibration_evidence(
    conn: sqlite3.Connection, evidence: CalibrationEvidence
) -> int:
    ...
```

Public `record_calibration_evidence()` opens a transaction and delegates to this helper.

- [ ] **Step 4: Version dashboard correction writes**

Add `revision` to the correction table through a lightweight migration:

```python
correction_columns = {
    row[1] for row in conn.execute("PRAGMA table_info(candidate_score_corrections)")
}
if "revision" not in correction_columns:
    conn.execute(
        "ALTER TABLE candidate_score_corrections ADD COLUMN revision INTEGER NOT NULL DEFAULT 1"
    )
```

In the correction upsert, set `revision = candidate_score_corrections.revision + 1`, reload `id, revision`, and append evidence with:

```python
CalibrationEvidence(
    source_type="dashboard_correction",
    source_id=f"{correction_id}:{revision}",
    candidate_type=correction.candidate_type,
    project_key=correction.project_key,
    role_key=role_key,
    candidate_id_at_submission=correction.candidate_id_at_submission,
    component_name=correction.component_name,
    failure_mode="subscore_override",
    target_kind="component",
    human_target=correction.corrected_component_score,
    submitted_agent_score=correction.agent_component_score,
    scoring_version=correction.scoring_version,
)
```

Keep `ui.py` behavior unchanged; its existing call to `upsert_candidate_correction()` now writes both records atomically. Add a UI integration assertion that a POSTed save results in one active evidence row.

- [ ] **Step 5: Backfill legacy rows idempotently**

Implement `_backfill_calibration_evidence(conn)` after all schema migrations. Expand `candidate_feedback` with `json_each(affected_components_json)`, join its candidate row for stable identity, and insert in ascending feedback ID so later evidence supersedes earlier evidence. Backfill each current correction as revision `1`. Guard every source row/component with `UNIQUE(source_type, source_id, component_name)` so initialization can run repeatedly.

Do not call the public method from `_ensure_schema()`; use `_record_calibration_evidence(conn, evidence)` to stay inside the current connection.

- [ ] **Step 6: Run targeted tests to verify GREEN**

Run the command from Step 2 plus:

```bash
.venv/bin/python -m pytest tests/test_cli_candidates.py tests/test_ui_candidates.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit routed evidence**

```bash
git add src/backstage_agent/storage.py src/backstage_agent/cli.py src/backstage_agent/ui.py \
  tests/test_candidate_storage.py tests/test_cli_candidates.py tests/test_ui_candidates.py
git commit -m "feat: retain latest calibration labels"
```

---

### Task 3: Residual Evaluation and Aggressive Bootstrap Proposals

**Files:**
- Modify: `src/backstage_agent/candidate_models.py`
- Modify: `src/backstage_agent/calibration.py`
- Modify: `src/backstage_agent/storage.py`
- Test: `tests/test_calibration.py`
- Test: `tests/test_candidate_storage.py`

**Interfaces:**
- Consumes: active evidence rows and current candidate `score_json` from Task 2; `load_scoring_rules()` for the current version.
- Produces: `EvaluatedCalibrationEvidence`, `evaluate_calibration_evidence(rows, current_version, calibration_date)`, `historical_weight(created_at, calibration_date) -> float`, `build_bootstrap_proposals(evaluated, scoring_version, calibration_date) -> tuple[list[tuple[CalibrationProposal, list[EvaluatedCalibrationEvidence]]], list[dict]]`, and `DecisionStore.record_calibration_proposal_idempotent(...) -> tuple[int, bool]`.

- [ ] **Step 1: Write failing residual and proposal tests**

Add:

```python
def test_evaluate_component_evidence_uses_current_score():
    rows = [{
        "id": 1,
        "candidate_type": "role",
        "project_key": "p",
        "role_key": "r",
        "component_name": "role_value",
        "target_kind": "component",
        "human_target": 8,
        "current_component_score": 15,
        "current_overall_score": 80,
        "current_scoring_version": "v2",
        "created_at": "2026-08-01 00:00:00",
    }]
    evaluated, excluded = evaluate_calibration_evidence(rows, "v2", date(2026, 8, 4))
    assert evaluated[0].residual == -7
    assert excluded == []


def test_incompatible_current_version_is_excluded():
    rows = [{**row, "current_scoring_version": "v1"}]
    evaluated, excluded = evaluate_calibration_evidence(rows, "v2", date(2026, 8, 4))
    assert evaluated == []
    assert excluded[0]["reason"] == "candidate_not_scored_with_current_rules"


def test_bootstrap_proposal_is_bounded_at_five_points():
    evaluated = [
        EvaluatedCalibrationEvidence(1, ("role", f"p-{i}", f"r-{i}", "role_value"), "role_value", -12)
        for i in range(3)
    ]
    proposals, excluded = build_bootstrap_proposals(
        evaluated, scoring_version="v2", calibration_date=date(2026, 8, 4)
    )
    proposal, supporting = proposals[0]
    assert proposal.maturity_stage == "bootstrap"
    assert proposal.example_count == 3
    assert proposal.proposed_adjustment == -5
    assert len(supporting) == 3
    assert excluded == []


def test_adjusted_current_scores_reduce_residual_pressure():
    before = build_bootstrap_proposals(_evaluated([-7, -6]), "v1", date(2026, 8, 4))[0][0][0]
    after = build_bootstrap_proposals(_evaluated([-2, -1]), "v2", date(2026, 8, 4))[0][0][0]
    assert before.proposed_adjustment == -5
    assert after.proposed_adjustment == -2


@pytest.mark.parametrize(
    ("created_at", "expected"),
    [
        ("2026-07-05 00:00:00", 1.00),
        ("2026-07-04 00:00:00", 0.70),
        ("2026-05-05 00:00:00", 0.70),
        ("2026-05-04 00:00:00", 0.40),
        ("2026-02-05 00:00:00", 0.40),
        ("2026-02-04 00:00:00", 0.20),
    ],
)
def test_historical_weight_boundaries(created_at, expected):
    assert historical_weight(created_at, date(2026, 8, 4)) == expected


def test_five_recent_labels_make_old_evidence_stability_only():
    evaluated = _dated_evidence(
        recent_residuals=[5, 5, 5, 5, 5],
        old_residuals=[-20],
    )
    proposals, excluded = build_bootstrap_proposals(
        evaluated, "v2", date(2026, 8, 4)
    )
    proposal, supporting = proposals[0]
    assert proposal.proposed_adjustment == 5
    assert proposal.effective_weight == 5.0
    assert [item.weight for item in supporting if item.age_days > 90] == [0.0]
    assert excluded == []
```

- [ ] **Step 2: Run tests to verify RED**

```bash
.venv/bin/python -m pytest tests/test_calibration.py -v
```

Expected: FAIL because residual evaluation and bounded bootstrap proposals do not exist.

- [ ] **Step 3: Add evaluation and proposal models**

Add:

```python
@dataclass(frozen=True)
class EvaluatedCalibrationEvidence:
    evidence_id: int
    stable_key: tuple[str, str, str, str]
    component_name: str
    residual: int
    created_at: datetime
    age_days: int
    weight: float


@dataclass(frozen=True)
class CalibrationProposal:
    pattern_key: str
    example_count: int
    average_delta: float
    affected_component: str
    failure_mode: str
    proposal_text: str
    scoring_version: str = ""
    maturity_stage: str = "bootstrap"
    proposed_adjustment: int = 0
    effective_weight: float = 0.0
    evidence_fingerprint: str = ""
    status: str = "proposed"
```

Retain defaults so existing callers and stored-proposal tests remain compatible.

- [ ] **Step 4: Implement residual evaluation**

Have `DecisionStore.active_calibration_evidence()` join the newest candidate row for the same stable identity and expose:

- `current_scoring_version`;
- `current_overall_score`;
- `current_component_score` from `json_extract(score_json, '$.subscores.' || component_name)`.

Implement `evaluate_calibration_evidence()` so component targets compare with `current_component_score`, overall targets compare with `current_overall_score`, missing scores receive `current_score_unavailable`, and version mismatches receive `candidate_not_scored_with_current_rules`. Parse SQLite timestamps as UTC-neutral stored timestamps, calculate whole `age_days` relative to the injected `calibration_date`, and reject future timestamps with `evidence_timestamp_in_future`.

- [ ] **Step 5: Implement bootstrap proposal calculation**

Implement `historical_weight()` with inclusive day ranges `0-30 -> 1.00`, `31-90 -> 0.70`, `91-180 -> 0.40`, and `181+ -> 0.20`. Group evaluated rows by component and deduplicate by `stable_key`. If the group contains at least five items aged 0-30 days, set every item older than 90 days to weight `0.00` while retaining it as stability-only supporting evidence.

For 1-5 distinct candidates, calculate `round(sum(residual * weight) / sum(weight))` and clamp it to `[-5, 5]`. Store `effective_weight=sum(weight)`. Generate the evidence fingerprint with SHA-256 over sorted strings of `evidence_id:residual:weight`, and include the scoring version. This makes unchanged reruns idempotent while allowing a new proposal when evidence crosses a defined age boundary. Set proposal text to:

```python
f"Bootstrap proposal: adjust {component.replace('_', ' ')} by "
f"{adjustment:+d} points from {len(group)} active candidate labels."
```

Do not generate learning or mature proposals; return an excluded summary with reason `future_maturity_stage_not_implemented` for groups above five.

- [ ] **Step 6: Persist proposals and evidence links idempotently**

Add these columns to `calibration_proposals` with lightweight migrations: `scoring_version`, `maturity_stage`, `proposed_adjustment`, `effective_weight`, and `evidence_fingerprint`. Add a unique index on `(pattern_key, scoring_version, evidence_fingerprint)`.

Create:

```sql
CREATE TABLE IF NOT EXISTS calibration_proposal_evidence (
  proposal_id INTEGER NOT NULL,
  evidence_id INTEGER NOT NULL,
  residual INTEGER NOT NULL,
  age_days INTEGER NOT NULL,
  evidence_weight REAL NOT NULL,
  PRIMARY KEY(proposal_id, evidence_id),
  FOREIGN KEY(proposal_id) REFERENCES calibration_proposals(id),
  FOREIGN KEY(evidence_id) REFERENCES candidate_calibration_evidence(id)
);
```

Implement:

```python
def record_calibration_proposal_idempotent(
    self,
    proposal: CalibrationProposal,
    evidence: list[EvaluatedCalibrationEvidence],
) -> tuple[int, bool]:
```

Use `INSERT ... ON CONFLICT DO NOTHING`, select the stable proposal ID, insert evidence links including `age_days` and `evidence_weight` with `ON CONFLICT DO NOTHING`, and return `(proposal_id, cursor.rowcount == 1)`.

- [ ] **Step 7: Run calibration and storage tests to verify GREEN**

```bash
.venv/bin/python -m pytest tests/test_calibration.py tests/test_candidate_storage.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit calibration behavior**

```bash
git add src/backstage_agent/candidate_models.py src/backstage_agent/calibration.py \
  src/backstage_agent/storage.py tests/test_calibration.py tests/test_candidate_storage.py
git commit -m "feat: add bootstrap residual calibration"
```

---

### Task 4: Idempotent CLI Output and Documentation

**Files:**
- Modify: `src/backstage_agent/cli.py`
- Modify: `tests/test_cli_candidates.py`
- Modify: `README.md`
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/module-guide.md`

**Interfaces:**
- Consumes: calibration evaluation, bootstrap proposal builder, and idempotent persistence from Task 3.
- Produces: `_calibration_patterns(store=None, rules=None) -> str` and stable JSON output for manual review.

- [ ] **Step 1: Write failing CLI tests**

Add a real temporary-store test that invokes `_calibration_patterns(store=store, rules={"version": "v2"})` twice and asserts:

```python
first = json.loads(_calibration_patterns(store=store, rules={"version": "v2"}))
second = json.loads(_calibration_patterns(store=store, rules={"version": "v2"}))

assert first["proposals"][0]["created"] is True
assert second["proposals"][0]["created"] is False
assert first["proposals"][0]["maturity_stage"] == "bootstrap"
assert first["proposals"][0]["proposed_adjustment"] == -5
assert first["active_evidence_count"] == 3
assert second["message"] == "No new calibration proposal was needed."
```

- [ ] **Step 2: Run the test to verify RED**

```bash
.venv/bin/python -m pytest tests/test_cli_candidates.py -k calibration -v
```

Expected: FAIL because `_calibration_patterns()` prints legacy grouped patterns and always inserts proposals.

- [ ] **Step 3: Replace the CLI orchestration**

Change the helper to accept injectable dependencies and return JSON:

```python
def _calibration_patterns(store=None, rules=None) -> str:
    settings = load_settings() if store is None else None
    store = store or DecisionStore(settings.database_path)
    rules = rules or load_scoring_rules()
    current_version = str(rules["version"])
    rows = store.active_calibration_evidence()
    calibration_date = date.today()
    evaluated, excluded = evaluate_calibration_evidence(
        rows, current_version, calibration_date
    )
    proposals, maturity_exclusions = build_bootstrap_proposals(
        evaluated, scoring_version=current_version, calibration_date=calibration_date
    )
    output = []
    for proposal, supporting_evidence in proposals:
        proposal_id, created = store.record_calibration_proposal_idempotent(
            proposal, supporting_evidence
        )
        output.append({
            "proposal_id": proposal_id,
            "pattern_key": proposal.pattern_key,
            "active_role_count": proposal.example_count,
            "maturity_stage": proposal.maturity_stage,
            "proposed_adjustment": proposal.proposed_adjustment,
            "average_residual": proposal.average_delta,
            "effective_evidence_weight": proposal.effective_weight,
            "created": created,
            "status": proposal.status,
        })
    payload = {
        "scoring_version": current_version,
        "active_evidence_count": len(rows),
        "excluded_evidence": [*excluded, *maturity_exclusions],
        "proposals": output,
        "message": (
            "No new calibration proposal was needed."
            if output and not any(item["created"] for item in output)
            else "Calibration proposals evaluated."
        ),
    }
    return json.dumps(payload, indent=2)
```

Adjust `main()` to `print(_calibration_patterns())`.

- [ ] **Step 4: Update operating documentation**

Update README calibration instructions to state that:

- the latest feedback for a role/component replaces its active predecessor;
- history is retained;
- bootstrap proposals use 1-5 distinct candidates and are capped at ±5;
- active historical evidence uses the documented 1.00/0.70/0.40/0.20 age weights;
- five recent labels make evidence older than 90 days stability-only;
- unchanged reruns do not create duplicates;
- proposals remain manual and do not rewrite rules.

Update `PROJECT_STATE.md` current capabilities and known limitations. Add learning/mature calibration with consistency and outlier resistance to recommended next steps. Add an Unreleased changelog entry for normalized evidence, supersession, residual evaluation, and idempotent proposals. Update the calibration entry in `docs/module-guide.md`.

- [ ] **Step 5: Run targeted tests to verify GREEN**

```bash
.venv/bin/python -m pytest \
  tests/test_candidate_models.py \
  tests/test_candidate_storage.py \
  tests/test_calibration.py \
  tests/test_cli_candidates.py \
  tests/test_ui_candidates.py -v
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 7: Run a disposable CLI smoke test**

Use a temporary SQLite database through the repository's settings override, insert fixture candidates/evidence with the tested storage APIs, and run:

```bash
BACKSTAGE_DATABASE_PATH=/tmp/backstage-calibration-smoke.sqlite3 \
  .venv/bin/python -m backstage_agent.cli calibration-patterns
```

Expected: valid JSON containing `scoring_version`, `active_evidence_count`, `excluded_evidence`, `proposals`, and `message`. Do not use the user's production database for this smoke test.

- [ ] **Step 8: Commit the CLI and documentation**

```bash
git add src/backstage_agent/cli.py tests/test_cli_candidates.py README.md \
  PROJECT_STATE.md CHANGELOG.md docs/module-guide.md
git commit -m "feat: expose idempotent bootstrap calibration"
```

---

## Final Verification Checklist

- [ ] Confirm `git status --short` contains no unrelated modifications.
- [ ] Confirm two submissions for one stable role/component produce one active label and two historical rows.
- [ ] Confirm three different roles count as three examples.
- [ ] Confirm a repeat run with unchanged evidence and scoring version inserts no proposal.
- [ ] Confirm changing the scoring version and rescoring candidates recalculates residuals before proposing another adjustment.
- [ ] Confirm historical weights change only at the 30/90/180-day boundaries.
- [ ] Confirm five recent labels prevent evidence older than 90 days from driving the adjustment while retaining it in proposal evidence.
- [ ] Confirm no command modifies `scoring_rules.json` automatically.
- [ ] Confirm the full pytest suite passes.
- [ ] Confirm live Backstage access, macOS notifications, and the production SQLite database were not needed or modified.
