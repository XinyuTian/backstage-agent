# Score Review Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the candidate card wall with an English score-review workbench that compares extracted evidence with agent component scores, saves one current correction per candidate identity and component, and overlays corrected display scores without mutating official candidate rows.

**Architecture:** Keep `candidates` as the immutable record of each scoring run and add `candidate_score_corrections` as a current-state projection keyed by stable candidate identity plus component. Store a resolved scoring snapshot in each new `score_json`, use one shared server-side recomputation helper for production and corrected display scores, and treat corrections from incompatible component maxima as stale until the user reconfirms or resets them. Preserve the existing append-only `candidate_feedback` CLI path; the new workbench and its calibration patterns use only the latest component corrections.

**Tech Stack:** Python 3, dataclasses, SQLite through `DecisionStore`, `http.server`, server-rendered HTML/CSS with small inline JavaScript, JSON, pytest.

## Global Constraints

- All workbench labels, headings, buttons, empty states, validation messages, notices, and table headers must be English.
- `candidates.overall_score`, `candidates.score_band`, `candidates.score_json`, rank, and draft suggestion remain official agent outputs and must not be mutated by UI corrections.
- Each stable candidate identity and component has at most one current correction; saving again overwrites only that component.
- Stable identity is `(candidate_type, project_key, role_key)`. Project-only candidates use an empty `role_key`.
- A correction reason belongs to one component and is optional.
- Overall is read-only and is always recomputed from agent subscores plus active component corrections and the candidate's saved cap values.
- Caps are display-only in v1 and cannot be edited or disputed from this UI.
- Corrections with unchanged component maxima remain active across scoring-version changes and show a version warning.
- Corrections whose component maximum changed are stale, do not affect displayed overall, and require explicit reconfirmation or reset.
- Calibration treats each current candidate/component correction as one example regardless of how many times it was edited.
- Preserve the existing `candidate-feedback` CLI and `candidate_feedback` rows; do not delete or reinterpret them in this change.
- Do not add score sorting in v1. Workbench candidates use effective project date descending, then candidate id descending.
- Do not perform live Backstage, model-provider, notification, or launchd actions while implementing this plan.

## File Structure

- Modify `src/backstage_agent/candidate_models.py`: scoring snapshot and component-correction data structures.
- Modify `src/backstage_agent/scoring.py`: resolved snapshot creation and shared overall/band recomputation.
- Modify `src/backstage_agent/storage.py`: correction schema, stable-key UPSERT/reset helpers, correction aggregation, and date-ordered workbench query.
- Modify `src/backstage_agent/calibration.py`: build proposals from component deltas without requiring coarse overall feedback taxonomy.
- Modify `src/backstage_agent/cli.py`: have `calibration-patterns` include current component-correction patterns while preserving legacy feedback patterns.
- Modify `src/backstage_agent/ui.py`: workbench view model, routes, validation, rendering, and progressive-enhancement preview.
- Modify `tests/test_candidate_models.py`: serialization/default coverage for new model fields.
- Modify `tests/test_candidate_scoring.py`: snapshot and shared-recomputation contract.
- Modify `tests/test_candidate_storage.py`: schema, stable identity, per-component UPSERT/reset, stale inputs, and workbench ordering.
- Modify `tests/test_calibration.py`: proposal behavior for current component corrections.
- Modify `tests/test_cli_candidates.py`: calibration command compatibility.
- Replace the card-wall expectations in `tests/test_ui_candidates.py`: workbench rendering, independent component POSTs, validation, reset, stale/reconfirm, redirect, and corrected display.
- Create `docs/superpowers/specs/2026-07-24-score-review-workbench-design.md`: durable product and data-semantics design note.
- Modify `README.md`: dashboard workflow.
- Modify `PROJECT_STATE.md`: current workbench and correction behavior.
- Modify `CHANGELOG.md`: user-visible workbench and scoring snapshot changes.
- Modify `docs/module-guide.md`: correction storage and workbench ownership.

---

### Task 1: Snapshot the Resolved Scoring Contract and Share Recalculation

**Files:**
- Modify: `tests/test_candidate_scoring.py`
- Modify: `tests/test_candidate_models.py`
- Modify: `src/backstage_agent/candidate_models.py`
- Modify: `src/backstage_agent/scoring.py`

**Interfaces:**
- Produces: `ScoringSnapshot`
- Produces: `build_scoring_snapshot(rules: dict) -> ScoringSnapshot`
- Produces: `recompute_overall_from_subscores(subscores: dict[str, int], score_caps: list[str], snapshot: ScoringSnapshot) -> tuple[int, ScoreBand]`
- Changes: `CandidateScore.scoring_snapshot: ScoringSnapshot | None`

- [ ] **Step 1: Write failing snapshot and recomputation tests**

Add tests that prove production and display recomputation share the same resolved values:

```python
def test_scoring_snapshot_resolves_weights_caps_and_bands(rules):
    snapshot = build_scoring_snapshot(rules)

    assert snapshot.version == rules["version"]
    assert snapshot.component_maxima == rules["component_weights"]
    assert snapshot.cap_values == rules["score_caps"]
    assert snapshot.band_thresholds["strong_candidate"] == 75


def test_recompute_overall_merges_sum_cap_clamp_and_band(rules):
    snapshot = build_scoring_snapshot(rules)

    overall, band = recompute_overall_from_subscores(
        {"role_value": 60, "project_value": 30},
        ["missing_critical_data"],
        snapshot,
    )

    assert overall == rules["score_caps"]["missing_critical_data"]
    assert band is ScoreBand.MAYBE_REVIEW


def test_score_candidate_uses_shared_recomputation(monkeypatch, features, matches, rules):
    calls = []
    original = scoring.recompute_overall_from_subscores

    def spy(subscores, score_caps, snapshot):
        calls.append((subscores, score_caps, snapshot))
        return original(subscores, score_caps, snapshot)

    monkeypatch.setattr(scoring, "recompute_overall_from_subscores", spy)
    score = scoring.score_candidate(features, matches, rules)

    assert len(calls) == 1
    assert score.scoring_snapshot.version == rules["version"]
```

Also update direct `CandidateScore(...)` fixtures to rely on a default `None` snapshot so existing callers remain source-compatible.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_scoring.py tests/test_candidate_models.py -v
```

Expected: FAIL because the snapshot type and shared helper do not exist.

- [ ] **Step 3: Add the snapshot model**

Add to `candidate_models.py`:

```python
@dataclass(frozen=True)
class ScoringSnapshot:
    version: str
    component_maxima: dict[str, int]
    cap_values: dict[str, int]
    band_thresholds: dict[str, int]


@dataclass(frozen=True)
class CandidateScore:
    # Preserve the existing fields in their current order.
    scoring_snapshot: ScoringSnapshot | None = None
```

Because `scoring_snapshot` has a default, place it after all current non-default fields.

- [ ] **Step 4: Implement the shared scoring helpers**

Add to `scoring.py`:

```python
def build_scoring_snapshot(rules: dict) -> ScoringSnapshot:
    return ScoringSnapshot(
        version=str(rules["version"]),
        component_maxima={
            str(name): int(value)
            for name, value in rules["component_weights"].items()
        },
        cap_values={
            str(name): int(value)
            for name, value in rules["score_caps"].items()
        },
        band_thresholds={
            str(band["name"]): int(band["min"])
            for band in rules["bands"]
        },
    )


def recompute_overall_from_subscores(
    subscores: dict[str, int],
    score_caps: list[str],
    snapshot: ScoringSnapshot,
) -> tuple[int, ScoreBand]:
    raw_score = sum(int(value) for value in subscores.values())
    resolved_caps = [
        snapshot.cap_values[cap]
        for cap in score_caps
        if cap in snapshot.cap_values
    ]
    capped_score = min([raw_score, *resolved_caps]) if resolved_caps else raw_score
    overall = max(0, min(100, int(round(capped_score))))
    return overall, _band_for_score(overall, snapshot.band_thresholds)
```

Change `_band_for_score()` to consume the snapshot thresholds:

```python
def _band_for_score(score: int, thresholds: dict[str, int]) -> ScoreBand:
    if score >= thresholds["top_priority"]:
        return ScoreBand.TOP_PRIORITY
    if score >= thresholds["strong_candidate"]:
        return ScoreBand.STRONG_CANDIDATE
    if score >= thresholds["maybe_review"]:
        return ScoreBand.MAYBE_REVIEW
    if score >= thresholds["low_priority"]:
        return ScoreBand.LOW_PRIORITY
    return ScoreBand.NOT_WORTH_APPLYING_TODAY
```

In `score_candidate()`, build one snapshot, pass it to the helper, and persist it on `CandidateScore`. Remove the duplicate inline sum/cap/band calculation.

- [ ] **Step 5: Run focused and storage serialization tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_scoring.py tests/test_candidate_models.py tests/test_candidate_storage.py -v
```

Expected: PASS, including existing candidate fixture serialization.

- [ ] **Step 6: Commit the resolved scoring snapshot**

```bash
git add src/backstage_agent/candidate_models.py src/backstage_agent/scoring.py tests/test_candidate_models.py tests/test_candidate_scoring.py
git commit -m "feat: snapshot resolved candidate scoring rules"
```

---

### Task 2: Persist One Current Correction per Stable Candidate Component

**Files:**
- Modify: `tests/test_candidate_storage.py`
- Modify: `src/backstage_agent/candidate_models.py`
- Modify: `src/backstage_agent/storage.py`

**Interfaces:**
- Produces: `CandidateComponentCorrection`
- Produces: `DecisionStore.upsert_candidate_correction(correction: CandidateComponentCorrection) -> int`
- Produces: `DecisionStore.delete_candidate_correction(candidate_type: str, project_key: str, role_key: str, component_name: str) -> bool`
- Produces: `DecisionStore.corrections_for_candidate_keys(keys: list[tuple[str, str, str]]) -> dict[tuple[str, str, str], list[sqlite3.Row]]`

- [ ] **Step 1: Write failing per-component persistence tests**

Add a helper that creates two scored candidates with stable keys, then add:

```python
def test_correction_upsert_replaces_only_matching_candidate_component(tmp_path):
    store, candidate_id = _store_with_scored_role(tmp_path)
    identity = ("role", "project-key", "role-key")

    first_id = store.upsert_candidate_correction(
        CandidateComponentCorrection(
            candidate_type=identity[0],
            project_key=identity[1],
            role_key=identity[2],
            candidate_id_at_submission=candidate_id,
            component_name="role_value",
            agent_component_score=15,
            corrected_component_score=10,
            reason="Too generous",
            scoring_version="v1",
            component_max_at_correction=15,
        )
    )
    second_id = store.upsert_candidate_correction(
        CandidateComponentCorrection(
            candidate_type=identity[0],
            project_key=identity[1],
            role_key=identity[2],
            candidate_id_at_submission=candidate_id,
            component_name="role_value",
            agent_component_score=15,
            corrected_component_score=8,
            reason="Final value",
            scoring_version="v1",
            component_max_at_correction=15,
        )
    )
    store.upsert_candidate_correction(
        CandidateComponentCorrection(
            candidate_type=identity[0],
            project_key=identity[1],
            role_key=identity[2],
            candidate_id_at_submission=candidate_id,
            component_name="logistics",
            agent_component_score=8,
            corrected_component_score=6,
            reason="",
            scoring_version="v1",
            component_max_at_correction=10,
        )
    )

    rows = store.corrections_for_candidate_keys([identity])[identity]
    assert second_id == first_id
    assert {(row["component_name"], row["corrected_component_score"]) for row in rows} == {
        ("role_value", 8),
        ("logistics", 6),
    }
    assert next(row for row in rows if row["component_name"] == "role_value")["reason"] == "Final value"
```

Add separate tests for project-only identity, component reset, and correction survival after candidate id replacement.

- [ ] **Step 2: Run the storage tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_storage.py -v
```

Expected: FAIL because `CandidateComponentCorrection` and correction store methods do not exist.

- [ ] **Step 3: Add the correction model**

Add to `candidate_models.py`:

```python
@dataclass(frozen=True)
class CandidateComponentCorrection:
    candidate_type: str
    project_key: str
    role_key: str
    candidate_id_at_submission: int
    component_name: str
    agent_component_score: int
    corrected_component_score: int
    reason: str
    scoring_version: str
    component_max_at_correction: int
```

Do not add a persisted `status`; active versus stale is derived against the selected candidate's current snapshot so it cannot drift.

- [ ] **Step 4: Add the correction table and indexes**

Add to `_ensure_schema()`:

```sql
CREATE TABLE IF NOT EXISTS candidate_score_corrections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  candidate_type TEXT NOT NULL,
  project_key TEXT NOT NULL,
  role_key TEXT NOT NULL DEFAULT '',
  candidate_id_at_submission INTEGER NOT NULL,
  component_name TEXT NOT NULL,
  agent_component_score INTEGER NOT NULL,
  corrected_component_score INTEGER NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  scoring_version TEXT NOT NULL,
  component_max_at_correction INTEGER NOT NULL,
  UNIQUE(candidate_type, project_key, role_key, component_name)
);
```

Add:

```sql
CREATE INDEX IF NOT EXISTS idx_candidate_score_corrections_identity
ON candidate_score_corrections(candidate_type, project_key, role_key);
```

Do not create a foreign key to `candidates.id`; `candidate_id_at_submission` is audit metadata and must survive overwrite rescoring.

- [ ] **Step 5: Implement UPSERT, reset, and batch load**

Use SQLite `ON CONFLICT(candidate_type, project_key, role_key, component_name) DO UPDATE` to replace only:

```text
candidate_id_at_submission
agent_component_score
corrected_component_score
reason
scoring_version
component_max_at_correction
updated_at
```

Do not replace `created_at`. Normalize project-only `role_key` to `""`. Implement reset with the same four-part stable key and return `cursor.rowcount > 0`.

For `corrections_for_candidate_keys()`, issue one query for the requested candidate identities rather than one query per candidate. Return every requested key with an empty list when no correction exists.

- [ ] **Step 6: Run candidate model and storage tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_models.py tests/test_candidate_storage.py -v
```

Expected: PASS. Existing `candidate_feedback` tests must remain unchanged and pass.

- [ ] **Step 7: Commit current component correction persistence**

```bash
git add src/backstage_agent/candidate_models.py src/backstage_agent/storage.py tests/test_candidate_storage.py
git commit -m "feat: persist current component score corrections"
```

---

### Task 3: Build Corrected Candidate Views and Current-Correction Calibration Patterns

**Files:**
- Modify: `tests/test_candidate_storage.py`
- Modify: `tests/test_calibration.py`
- Modify: `tests/test_cli_candidates.py`
- Modify: `src/backstage_agent/storage.py`
- Modify: `src/backstage_agent/calibration.py`
- Modify: `src/backstage_agent/cli.py`

**Interfaces:**
- Produces: `DecisionStore.search_candidate_workbench_rows(query: str = "", band: str = "all", limit: int = 200) -> list[sqlite3.Row]`
- Produces: `DecisionStore.correction_patterns(min_examples: int = 2) -> list[sqlite3.Row]`
- Preserves: `DecisionStore.search_candidates(...)` ordering and CLI candidate output
- Preserves: `DecisionStore.feedback_patterns(...)` for legacy coarse feedback

- [ ] **Step 1: Write a failing date-order query test**

Create two projects with different `last_seen_date` values and candidates whose rank order is the reverse of date order:

```python
rows = store.search_candidate_workbench_rows()

assert [row["project_key"] for row in rows] == ["new-project", "old-project"]
assert rows[0]["effective_project_date"] == "2026-07-24"
```

Also assert the row exposes `last_seen_date`, `project_date`, and the complete candidate JSON fields needed by the UI.

- [ ] **Step 2: Write failing correction-pattern tests**

Save the same role/component three times and a second role/component once:

```python
patterns = store.correction_patterns(min_examples=2)

assert patterns[0]["affected_component"] == "role_value"
assert patterns[0]["failure_mode"] == "subscore_override"
assert patterns[0]["example_count"] == 2
assert patterns[0]["average_delta"] == pytest.approx(-4.5)
```

The first role must count once with only its final component delta. Optional reasons must not affect aggregation.

- [ ] **Step 3: Run the focused tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_storage.py tests/test_calibration.py tests/test_cli_candidates.py -v
```

Expected: FAIL because the workbench query and correction patterns do not exist.

- [ ] **Step 4: Implement the minimal workbench query**

Add a new query without modifying `search_candidates()`:

```sql
SELECT
  c.*,
  p.last_seen_date,
  p.project_date AS source_project_date,
  date(COALESCE(p.last_seen_date, p.project_date, p.created_at))
    AS effective_project_date
FROM candidates AS c
JOIN projects AS p ON p.id = c.source_project_id
{where}
ORDER BY
  date(COALESCE(p.last_seen_date, p.project_date, p.created_at)) DESC,
  c.id DESC
LIMIT ?
```

Keep the existing title/notice search and official-band filter behavior. Filtering remains based on official `score_band`; corrected-band filtering is out of scope for v1.

- [ ] **Step 5: Implement current correction aggregation**

Aggregate directly from `candidate_score_corrections`:

```sql
SELECT
  component_name AS affected_component,
  'subscore_override' AS failure_mode,
  COUNT(*) AS example_count,
  AVG(corrected_component_score - agent_component_score) AS average_delta
FROM candidate_score_corrections
GROUP BY component_name
HAVING COUNT(*) >= ?
ORDER BY
  ABS(AVG(corrected_component_score - agent_component_score)) DESC,
  COUNT(*) DESC
```

Do not include stale rows here because staleness depends on the newest candidate snapshot. Join the newest matching candidate by stable identity and include only corrections whose `component_max_at_correction` matches the current component maximum. Corrections with a changed scoring version but unchanged maximum remain eligible.

- [ ] **Step 6: Include correction patterns in the calibration command**

Keep legacy feedback patterns and add current correction patterns:

```python
patterns = [
    *store.feedback_patterns(),
    *store.correction_patterns(),
]
proposals = build_calibration_proposals(patterns)
```

Before proposal creation, merge rows with the same `(affected_component, failure_mode)` by weighted example count and average delta. Add a focused pure helper in `calibration.py`:

```python
def merge_calibration_patterns(pattern_groups: list[list]) -> list[dict]:
    totals: dict[tuple[str, str], dict[str, float | int | str]] = {}
    for patterns in pattern_groups:
        for row in patterns:
            component = str(row["affected_component"])
            failure_mode = str(row["failure_mode"])
            count = int(row["example_count"])
            key = (component, failure_mode)
            total = totals.setdefault(
                key,
                {
                    "affected_component": component,
                    "failure_mode": failure_mode,
                    "example_count": 0,
                    "weighted_delta": 0.0,
                },
            )
            total["example_count"] = int(total["example_count"]) + count
            total["weighted_delta"] = float(total["weighted_delta"]) + (
                float(row["average_delta"]) * count
            )

    merged = []
    for total in totals.values():
        count = int(total["example_count"])
        merged.append(
            {
                "affected_component": total["affected_component"],
                "failure_mode": total["failure_mode"],
                "example_count": count,
                "average_delta": float(total["weighted_delta"]) / count,
            }
        )
    return sorted(
        merged,
        key=lambda row: (abs(row["average_delta"]), row["example_count"]),
        reverse=True,
    )
```

This preserves CLI feedback while ensuring repeated edits to one component correction count once.

- [ ] **Step 7: Run storage, calibration, and CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_candidate_storage.py tests/test_calibration.py tests/test_cli_candidates.py -v
```

Expected: PASS with legacy CLI feedback tests unchanged.

- [ ] **Step 8: Commit workbench queries and calibration projection**

```bash
git add src/backstage_agent/storage.py src/backstage_agent/calibration.py src/backstage_agent/cli.py tests/test_candidate_storage.py tests/test_calibration.py tests/test_cli_candidates.py
git commit -m "feat: aggregate current component corrections"
```

---

### Task 4: Add Server-Side Correction Merge and Validation

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py`

**Interfaces:**
- Produces: `_candidate_workbench_view(row, corrections, current_rules) -> dict`
- Produces: `_save_component_correction_from_params(store, params) -> int`
- Produces: `_reset_component_correction_from_params(store, params) -> bool`
- Produces: `_reconfirm_component_correction_from_params(store, params) -> int`

- [ ] **Step 1: Write failing merge-view tests**

Use a candidate row with a complete scoring snapshot and test:

```python
view = _candidate_workbench_view(row, corrections=[], current_rules=rules)
assert view["display_overall"] == 86
assert view["display_band"] == "strong_candidate"
assert view["components"]["role_value"]["display_score"] == 15

view = _candidate_workbench_view(
    row,
    corrections=[correction_row("role_value", corrected=10, saved_max=15)],
    current_rules=rules,
)
assert view["components"]["role_value"]["display_score"] == 10
assert view["components"]["role_value"]["active"] is True
assert view["display_overall"] == 81
```

Add cases for:

- scoring version changed and maximum unchanged: active with version warning;
- maximum changed: stale, agent score used in overall;
- multiple active caps: minimum saved cap applied;
- legacy candidate without snapshot and matching current rules version: current rules fallback with compatibility warning;
- legacy candidate without snapshot and mismatched version: correction disabled with explicit warning.

- [ ] **Step 2: Write failing validation tests**

Add parameterized tests that reject:

```text
unknown component
non-integer correction
negative correction
correction above component maximum
missing candidate
client-supplied stable identity that does not match persisted candidate
save with unchanged agent value
reconfirm value outside the new maximum
```

Also assert an empty optional reason is accepted.

- [ ] **Step 3: Run UI unit tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -v
```

Expected: FAIL because the workbench merge and correction actions do not exist.

- [ ] **Step 4: Implement snapshot parsing and merge semantics**

In `_candidate_workbench_view()`:

1. Parse `score_json.subscores`, `score_json.score_caps`, and `score_json.scoring_snapshot`.
2. If the snapshot exists, use it exactly.
3. If no snapshot exists and `row["scoring_version"] == current_rules["version"]`, build a compatibility snapshot from current rules and add a warning.
4. If no compatible snapshot exists, show agent data but disable correction save/reconfirm.
5. Index current corrections by component.
6. Mark a correction stale only when its saved maximum differs from the current snapshot maximum.
7. Merge only active corrections.
8. Call `recompute_overall_from_subscores()` for display overall and band.
9. Keep official score, band, rank, and draft suggestion in separate `agent_*` fields.

- [ ] **Step 5: Implement authoritative save/reset/reconfirm validation**

For every POST:

- Parse only `candidate_id`, `component_name`, `corrected_score`, and optional `reason`.
- Load the candidate from the store; derive stable identity from the row rather than trusting form values.
- Load the candidate scoring snapshot through the same merge helper.
- Require an integer within `0..component_max`.
- Reject a save equal to the agent component score with `"Use Reset to return to the agent score."`
- Save one `CandidateComponentCorrection`.
- Reset with stable identity plus component.
- Reconfirm by updating `component_max_at_correction`, `scoring_version`, agent component score, corrected value, and optional reason.

Do not accept overall, caps, max points, agent score, project key, role key, scoring version, rank, band, or draft suggestion from the browser.

- [ ] **Step 6: Run UI and scoring tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py tests/test_candidate_scoring.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit server-side workbench semantics**

```bash
git add src/backstage_agent/ui.py tests/test_ui_candidates.py
git commit -m "feat: validate component score corrections"
```

---

### Task 5: Replace the Card Wall with the Score Review Workbench

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py`

**Interfaces:**
- Changes: GET `/candidates?q=&band=&id=` renders the workbench
- Adds: POST `/candidate-correction`
- Adds: POST `/candidate-correction/reset`
- Adds: POST `/candidate-correction/reconfirm`
- Removes: workbench use of POST `/candidate-feedback`; preserve CLI feedback code outside the dashboard

- [ ] **Step 1: Write failing route and rendering tests**

Replace card-wall assertions with:

```python
assert _post_route("/candidate-correction") == "candidate_correction"
assert _post_route("/candidate-correction/reset") == "candidate_correction_reset"
assert _post_route("/candidate-correction/reconfirm") == "candidate_correction_reconfirm"

html = _render_candidates_index(store, {"id": ["1"]})
assert 'class="score-workbench"' in html
assert 'class="candidate-list"' in html
assert 'class="evidence-pane"' in html
assert 'class="score-pane"' in html
assert "Overall" in html
assert "Agent" in html
assert "Correction" in html
assert "Reason (optional)" in html
assert "Save" in html
assert "Reset" in html
assert "Human score" not in html
assert 'lang="en"' in html
```

Add tests for no candidates, selected id not in filtered results, project-only candidates, malformed optional JSON, corrected list color/band, stale correction controls, and absence of Chinese UI strings.

- [ ] **Step 2: Write failing redirect-preservation tests**

After save/reset/reconfirm, assert a `303` destination shaped like:

```text
/candidates?id=12&q=Lead&band=strong_candidate&correction=saved
```

Only allow local query values created with `urllib.parse.urlencode`; do not accept a browser-provided redirect URL.

- [ ] **Step 3: Run UI tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -v
```

Expected: FAIL with card-wall markup and missing routes.

- [ ] **Step 4: Implement the workbench shell**

Render:

- a compact left list using corrected display overall, corrected display band/color, effective date, candidate type, and title;
- the selected candidate on the right;
- a vertically scrollable evidence pane containing notice text, extracted features, requirement matches, positive/negative drivers, and score trace;
- a separately scrolling/pinned score pane;
- an Overall summary showing corrected overall prominently and original agent overall when they differ;
- active cap labels and resolved values, or `"No active caps"`;
- one component row per snapshot component with max points, agent score, correction field, its own optional reason, and independent Save/Reset controls;
- stale rows with old max, new max, inactive status, Reconfirm, and Reset;
- agent rank and draft suggestion labeled explicitly as agent outputs, or visually de-emphasized.

Do not render raw JSON blobs. Render dictionaries and lists through escaped structured helpers.

- [ ] **Step 5: Add progressive-enhancement score preview**

Embed only server-derived numeric data in escaped `data-*` attributes:

```text
agent component scores
component maxima
active corrected values
resolved active cap values
band thresholds
```

On correction input:

1. replace only that component in the client-side merged map;
2. sum merged component values;
3. apply the minimum active cap;
4. clamp to `0..100`;
5. update Overall and band/color preview.

The JavaScript preview is advisory. POST validation and the shared Python helper remain authoritative.

- [ ] **Step 6: Add responsive and independent-scroll CSS**

Desktop:

- left list approximately 32%;
- right pane approximately 68%;
- evidence pane consumes flexible height and scrolls vertically;
- score pane remains visible at the bottom and scrolls internally when necessary.

At `max-width: 800px`, stack the candidate list above the selected detail and remove fixed pane heights so all controls remain reachable.

- [ ] **Step 7: Run candidate UI and storage tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py tests/test_candidate_storage.py -v
```

Expected: PASS.

- [ ] **Step 8: Commit the score review workbench**

```bash
git add src/backstage_agent/ui.py tests/test_ui_candidates.py
git commit -m "feat: replace candidate cards with score workbench"
```

---

### Task 6: Document the Workbench and Correction Semantics

**Files:**
- Create: `docs/superpowers/specs/2026-07-24-score-review-workbench-design.md`
- Modify: `README.md`
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/module-guide.md`

**Interfaces:**
- Documents: immutable agent score versus current correction versus displayed score
- Documents: per-component overwrite, reset, version warning, stale/reconfirm, and calibration behavior

- [ ] **Step 1: Write the durable design note**

The design note must state:

- the English left-list/right-detail workbench layout;
- component rows with independent Save/Reset and optional per-component reasons;
- stable identity `(candidate_type, project_key, role_key, component_name)`;
- why `candidate_id_at_submission` is audit metadata rather than identity;
- immutable official candidate rows;
- scoring snapshot contents;
- active versus stale compatibility rules;
- calibration counting only the current correction once;
- preservation of legacy CLI feedback;
- v1 exclusions: cap editing, automatic rule mutation, correction-history UI, score sorting, and live Backstage actions.

- [ ] **Step 2: Update user-facing and current-state docs**

Update README dashboard instructions to describe:

```text
open /candidates
select a candidate
compare evidence and agent component scores
save or reset one component correction
review corrected Overall without changing the official score
```

Update `PROJECT_STATE.md` capabilities and known limitations. Add an Unreleased changelog entry for the scoring snapshot, correction projection, calibration aggregation, and workbench replacement. Update the module guide so future work starts in `ui.py`, `storage.py`, and `scoring.py`.

- [ ] **Step 3: Check documentation for obsolete card-wall language**

Run:

```bash
rg -n "candidate card|card wall|Human score|candidate-feedback" README.md PROJECT_STATE.md CHANGELOG.md docs src/backstage_agent/ui.py
```

Expected: no current dashboard documentation describes the removed coarse feedback form; historical changelog/spec references may remain.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md PROJECT_STATE.md CHANGELOG.md docs/module-guide.md docs/superpowers/specs/2026-07-24-score-review-workbench-design.md
git commit -m "docs: describe score review workbench"
```

---

### Task 7: Run Regression and Live-Local Verification

**Files:**
- Verify only; fix failures in the smallest relevant source/test file.

**Interfaces:**
- Verifies: scoring, persistence, calibration, CLI compatibility, server rendering, and local dashboard behavior

- [ ] **Step 1: Run the focused regression suite**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_candidate_models.py \
  tests/test_candidate_scoring.py \
  tests/test_candidate_storage.py \
  tests/test_calibration.py \
  tests/test_cli_candidates.py \
  tests/test_ui_candidates.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run the full suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS with no regressions.

- [ ] **Step 3: Start or restart the local dashboard using the repository's existing dashboard command**

Use the existing local dashboard workflow documented in README. Do not change launchd configuration and do not access Backstage.

Verify locally at `http://127.0.0.1:8765/candidates`:

- candidate list is date ordered;
- selecting a candidate changes the right pane;
- evidence and score panes scroll independently on desktop;
- saving one component changes only that component and corrected Overall;
- refresh preserves the correction;
- saving the same component again shows only the last value;
- correcting a second component preserves the first;
- Reset returns one component to its agent score;
- optional reason can be blank;
- active caps constrain corrected Overall;
- agent score, rank, and draft suggestion remain unchanged;
- no Chinese UI strings appear.

- [ ] **Step 4: Inspect the database invariants after local UI actions**

Run a read-only SQLite query through the existing Python environment and confirm:

```text
one candidate_score_corrections row per stable identity/component
candidates score_json and overall_score unchanged
candidate_feedback row count unchanged by workbench corrections
```

- [ ] **Step 5: Commit any verification-only fixes**

If verification required code changes:

```bash
git add \
  src/backstage_agent/candidate_models.py \
  src/backstage_agent/scoring.py \
  src/backstage_agent/storage.py \
  src/backstage_agent/calibration.py \
  src/backstage_agent/cli.py \
  src/backstage_agent/ui.py \
  tests/test_candidate_models.py \
  tests/test_candidate_scoring.py \
  tests/test_candidate_storage.py \
  tests/test_calibration.py \
  tests/test_cli_candidates.py \
  tests/test_ui_candidates.py
git commit -m "fix: address score workbench regressions"
```

If no files changed, do not create an empty commit.

## Completion Criteria

- New candidate scores contain resolved component maxima, cap values, and band thresholds.
- Production scoring and UI overlay use the same Python recomputation helper.
- One role/project-only component correction overwrites only itself.
- Repeated edits count as one current calibration example.
- Optional reasons remain attached to their individual components.
- Candidate overwrite rescoring does not orphan the correction identity.
- Unchanged maxima remain active across versions with a warning.
- Changed maxima become stale and require Reconfirm or Reset.
- Workbench corrections never mutate official candidate scores, rank, band, caps, or draft suggestion.
- Focused and full pytest suites pass.
- Local dashboard behavior is verified without live Backstage or model-provider actions.
