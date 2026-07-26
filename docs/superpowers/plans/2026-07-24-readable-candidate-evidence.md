# Readable Candidate Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace nested JSON-style evidence with a source-grounded, adaptive, single-column reading flow that contains enough role, project, logistics, compensation, requirement, match, and original-text information to make a decision.

**Architecture:** Add focused presentation helpers inside `src/backstage_agent/ui.py` that normalize the existing `notice`, `features`, and `requirement_matches` payloads into readable sections. Render those sections with semantic single-column HTML while preserving the existing workbench, score, divider, correction grid, routes, and persistence.

**Tech Stack:** Python 3, server-rendered HTML/CSS, pytest.

## Global Constraints

- Evidence is one vertical column; no multi-column evidence grid or side-by-side label/value table.
- Do not render numbered wrapper headings such as `Requirement 1`.
- Use normal-weight body text and reserve stronger weight for the candidate title and small section headings.
- Use only stored notice, feature, and requirement-match data; never invent project or role descriptions.
- Omit empty sections and low-value technical wrappers.
- Preserve a collapsed original listing at the bottom.
- Do not change filtering, scoring, dates, adjustable divider, corrections, storage schema, scheduling, notifications, or external integrations.
- Preserve unrelated working-tree changes.

---

### Task 1: Evidence Presentation Model

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py`

**Interfaces:**
- Produces: `_candidate_evidence_sections(view: dict) -> list[dict[str, object]]`.
- Produces: `_flatten_requirements(value: object) -> list[dict[str, str]]`.
- Consumes: `view["notice"]`, `view["features"]`, and `view["requirement_matches"]`.

- [ ] **Step 1: Add representative failing tests**

Build a view containing:

```python
features = {
    "role_type": "Background / Extra",
    "project_type": "Film",
    "role_description": "Performs as one of the enemy soldiers.",
    "project_description": "Independent action-comedy short.",
    "requirements": {
        "requirement_1": {
            "description": "Age 18+",
            "importance": "mandatory",
            "evidence": "Background / Extra, 18+",
        },
        "requirement_2": {
            "description": "Stunt experience",
            "importance": "mandatory",
            "evidence": "Stunt experience a must.",
        },
    },
    "compensation": {"amount": "$100", "type": "flat rate"},
}
```

Include notice location, shooting locations/dates, compensation, description,
and raw text plus representative requirement matches.

Assert the presentation model contains readable Role, Project, Where and when,
Compensation, Requirements, and Decision notes content without keys named
`requirement_1` or headings named `Requirement 1`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "evidence_sections or flatten_requirements" -q
```

Expected: FAIL because the presentation helpers do not exist.

- [ ] **Step 3: Implement requirement flattening**

Support requirement payloads represented as:

- dictionaries keyed by `requirement_1`, `requirement_2`, and similar wrappers;
- plain lists of dictionaries;
- plain strings.

Return only useful fields:

```python
{
    "description": "...",
    "importance": "...",
    "evidence": "...",
}
```

Discard empty wrappers and avoid duplicate description/evidence text.

- [ ] **Step 4: Implement adaptive section construction**

Build sections only when source values exist:

- Role: role description, role type, and relevant role-level source text.
- Project: project description and project type.
- Where and when: location, shooting locations, and shooting dates.
- Compensation: feature compensation plus notice compensation/union terms,
  deduplicated.
- Requirements: flattened requirements.
- Decision notes: requirement-match status, local value, evidence, and reason
  rewritten through existing `_humanize` labels without exposing technical
  wrapper keys.

Prefer explicit structured fields; fall back to source description only where
it is actually stored. Do not synthesize prose that the payload does not
support.

- [ ] **Step 5: Run focused and UI tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -q
```

Expected: all candidate UI tests pass.

### Task 2: Single-Column Evidence Rendering

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py`
- Modify: `PROJECT_STATE.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/module-guide.md`

**Interfaces:**
- Consumes: `_candidate_evidence_sections(view)`.
- Produces: `_render_readable_evidence(view) -> str`.
- Replaces: the existing generic `_render_json_section` evidence path in candidate detail.

- [ ] **Step 1: Add failing renderer tests**

Assert rendered HTML:

```python
assert 'class="readable-evidence"' in html
assert 'class="evidence-section"' in html
assert "Role" in html
assert "Project" in html
assert "Where and when" in html
assert "Compensation" in html
assert "Requirements" in html
assert "Original listing text" in html
assert "<details" in html
assert "Requirement 1" not in html
assert "Requirement Key" not in html
assert 'class="evidence-grid"' not in html
```

Use an HTML parser to confirm evidence sections are direct vertical siblings,
not columns. Add a sparse-payload test proving empty sections are omitted.

- [ ] **Step 2: Run renderer tests and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "readable_evidence" -q
```

Expected: FAIL against the generic nested renderer.

- [ ] **Step 3: Render readable sections**

Use semantic section markup:

```html
<div class="readable-evidence">
  <section class="evidence-section">
    <h3>Role</h3>
    <p>...</p>
  </section>
  ...
  <details class="original-listing">
    <summary>Original listing text</summary>
    <div class="original-listing-text">...</div>
  </details>
</div>
```

Requirements render as one plain `<ul>`. Each item may show a subdued
importance/evidence line, but no numbered wrapper label. Decision notes use
plain text or bullets and omit repeated technical field names.

- [ ] **Step 4: Replace evidence CSS**

Remove the two-column `.evidence-grid` rules. Add:

```css
.readable-evidence { max-width: 760px; }
.evidence-section { padding: 16px 0; border-bottom: 1px solid #e6e1d8; }
.evidence-section h3 { font-size: 12px; font-weight: 650; }
.evidence-section p,
.evidence-section li { font-weight: 400; line-height: 1.6; }
```

Keep all evidence in one column at every viewport width.

- [ ] **Step 5: Update documentation**

Document the adaptive single-column evidence flow, flattened requirements,
collapsed original source text, and source-grounded/no-invention behavior.

- [ ] **Step 6: Run full verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -q
.venv/bin/python -m pytest -q
git diff --check
```

Expected: all tests pass and the diff is clean.

- [ ] **Step 7: Verify live dashboard**

Restart the launchd-managed UI and inspect a real subject-date candidate:

- evidence is one column;
- numbered requirement wrappers are absent;
- typography uses restrained bold;
- role, project, location/dates, pay, requirements, decision notes, and
  original text appear when present;
- the correction grid and divider remain unchanged.

Do not submit corrections or trigger external actions.
