# Adjustable Workbench Divider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a non-persistent, accessible draggable divider with a default 22/78 candidate-list/detail split.

**Architecture:** Keep the feature entirely in the existing server-rendered `src/backstage_agent/ui.py`. Insert a separator between the two panels, drive the grid width with a CSS custom property, and use pointer plus keyboard events to update that property within pixel constraints.

**Tech Stack:** Python 3, server-rendered HTML/CSS/JavaScript, pytest.

## Global Constraints

- Default desktop split is exactly 22% left and 78% right.
- Left panel minimum is 220 pixels; right panel minimum is 480 pixels.
- Width is not persisted across reloads.
- Mobile layout remains stacked and hides the divider.
- Do not change candidate filtering, scoring, corrections, storage, scheduling, notifications, or external integrations.
- Preserve unrelated working-tree changes.

---

### Task 1: Accessible Divider Markup and Styling

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py`

**Interfaces:**
- Produces: a `.workbench-divider` element between `.candidate-list` and `.candidate-detail`.
- Produces: `--candidate-list-width: 22%` on `.score-workbench`.

- [ ] **Step 1: Write failing rendering tests**

Add assertions:

```python
assert 'class="workbench-divider"' in html
assert 'role="separator"' in html
assert 'aria-orientation="vertical"' in html
assert 'tabindex="0"' in html
assert "--candidate-list-width: 22%" in html
assert "minmax(220px, var(--candidate-list-width))" in html
assert "minmax(480px, 1fr)" in html
```

Also assert the divider appears in the workbench markup after the candidate
navigation and before candidate detail.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "divider" -q
```

Expected: FAIL because no divider exists.

- [ ] **Step 3: Implement minimal markup and CSS**

Render:

```html
<div class="workbench-divider" role="separator"
  aria-orientation="vertical" aria-label="Resize candidate panels"
  aria-valuemin="220"
  tabindex="0"></div>
```

Use:

```css
.score-workbench {
  --candidate-list-width: 22%;
  grid-template-columns:
    minmax(220px, var(--candidate-list-width))
    6px
    minmax(480px, 1fr);
}
.workbench-divider { cursor: col-resize; }
```

At the existing mobile breakpoint, restore one column and hide the divider.

- [ ] **Step 4: Run UI tests and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -q
```

Expected: all candidate UI tests pass.

### Task 2: Pointer and Keyboard Resizing

**Files:**
- Modify: `tests/test_ui_candidates.py`
- Modify: `src/backstage_agent/ui.py`
- Modify: `CHANGELOG.md`
- Modify: `PROJECT_STATE.md`

**Interfaces:**
- Consumes: `.score-workbench` and `.workbench-divider`.
- Updates: `--candidate-list-width` in pixels for the current page only.
- Updates: separator `aria-valuenow`.

- [ ] **Step 1: Write failing JavaScript contract tests**

Assert the rendered script includes:

```python
assert "pointerdown" in html
assert "pointermove" in html
assert "pointerup" in html
assert "setPointerCapture" in html
assert "ArrowLeft" in html
assert "ArrowRight" in html
assert '"Home"' in html
assert '"End"' in html
assert "220" in html
assert "480" in html
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "divider" -q
```

Expected: FAIL because resize behavior is missing.

- [ ] **Step 3: Implement pointer behavior**

On pointer down, capture the pointer and mark the divider active. On pointer
move, compute the pointer's position relative to the workbench:

```javascript
const minimumLeft = 220;
const maximumLeft = Math.max(minimumLeft, rect.width - 480 - divider.offsetWidth);
const leftWidth = Math.min(maximumLeft, Math.max(minimumLeft, event.clientX - rect.left));
workbench.style.setProperty('--candidate-list-width', `${leftWidth}px`);
```

Set `aria-valuenow` and `aria-valuemax` to pixel values during initialization
and update `aria-valuenow` after each resize. On pointer up/cancel, release the
active state.

- [ ] **Step 4: Implement keyboard behavior**

Use 16-pixel left/right increments. `Home` selects the 220-pixel minimum and
`End` selects the computed maximum. Prevent default scrolling for handled keys
and update both the CSS property and `aria-valuenow`.

- [ ] **Step 5: Update documentation**

Add concise Unreleased and current-capability notes describing the 22/78
default, drag/keyboard resizing, mobile behavior, and non-persistence.

- [ ] **Step 6: Run full verification**

Run:

```bash
.venv/bin/python -m pytest tests/test_ui_candidates.py -q
.venv/bin/python -m pytest -q
git diff --check
```

Expected: all tests pass and the diff is clean.

- [ ] **Step 7: Verify live behavior**

Restart the launchd UI, open the subject-date candidate view, and verify:

- the initial panel widths are approximately 22/78;
- dragging changes the widths;
- keyboard arrows change the widths;
- reloading restores 22/78;
- the divider is hidden in a mobile viewport.

Do not submit corrections or trigger external actions.
