# Task 2 Report: Pointer and Keyboard Resizing

## Status

Implemented pointer and keyboard resizing for the candidate workbench divider.
The split remains page-local and returns to the CSS 22/78 default on reload.

## RED evidence

Command:

```text
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "divider" -q
```

Result after adding the JavaScript contract test:

```text
.F
FAILED tests/test_ui_candidates.py::test_render_candidates_index_includes_divider_resize_interactions
assert "pointerdown" in html
1 failed, 1 passed, 21 deselected
```

The failure was expected because the divider had no resize script.

## GREEN evidence

Focused divider test after implementation:

```text
2 passed, 21 deselected in 0.03s
```

Candidate UI suite:

```text
23 passed in 0.04s
```

Full repository suite:

```text
128 passed in 2.74s
```

Diff validation:

```text
git diff --check
exit 0
```

## Implementation

- Pointer down captures the pointer and marks the divider active.
- Pointer movement clamps the list panel to a 220-pixel minimum while
  preserving at least 480 pixels for the detail panel.
- Pointer up or cancellation clears the active state.
- Left and right arrows resize in 16-pixel increments; Home and End select the
  computed minimum and maximum.
- `aria-valuenow` and `aria-valuemax` expose current pixel values.
- No width is persisted; mobile CSS continues to hide the divider.
- `CHANGELOG.md` and `PROJECT_STATE.md` describe the default split,
  interaction methods, mobile behavior, and non-persistence.

## Live verification limitation

The launchd UI kickstart command exited successfully, but
`http://127.0.0.1:8765/candidates` was not reachable afterward, and no in-app
browser session was available. Dragging, keyboard operation, reload reset, and
mobile viewport behavior were therefore not verified in the live dashboard.
No corrections or external actions were submitted.

## Review follow-up: responsive lifecycle

### RED

Command:

```text
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "divider_resize_lifecycle" -q
```

Result after adding the lifecycle contract test:

```text
FAILED tests/test_ui_candidates.py::test_divider_resize_lifecycle_reclamps_and_cleans_up_pointer_capture
assert "const synchronizeDivider = () =>" in html
1 failed, 23 deselected in 0.07s
```

This was the expected failure because viewport synchronization and
`lostpointercapture` cleanup were absent.

### GREEN

The same focused command after implementation:

```text
1 passed, 23 deselected in 0.03s
```

The rendered contract now requires a workbench `ResizeObserver` that invokes
the shared `setLeftWidth` clamping/ARIA helper on desktop, plus
`lostpointercapture` cleanup through the common drag-finishing function.
Mobile resizing keeps ARIA bounds synchronized without persisting or replacing
the last page-local pixel width; returning to desktop clamps that width against
the current 220-pixel/480-pixel panel bounds.

Final verification:

```text
.venv/bin/python -m pytest tests/test_ui_candidates.py -q
24 passed in 0.04s

.venv/bin/python -m pytest -q
129 passed in 2.73s

git diff --check
exit 0
```

The responsive contract was then tightened to cover workbench changes that do
not necessarily originate from a window resize. Before switching to a bounded
`ResizeObserver`, the focused test failed with:

```text
assert "new ResizeObserver(synchronizeDivider)" in html
1 failed, 23 deselected in 0.07s
```

After the observer implementation, the final verification above passed.

## Final review follow-up: content bounds and adjustment state

### RED

Command:

```text
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "content_bounds" -q
```

Result after adding the content-bound and adjustment-state contract:

```text
FAILED tests/test_ui_candidates.py::test_divider_uses_content_bounds_and_preserves_default_until_user_resize
assert "const contentWidth = workbench.clientWidth" in html
1 failed, 24 deselected in 0.07s
```

This was the expected failure: the old calculation used the outer
`getBoundingClientRect().width`, and responsive synchronization inferred state
from the currently rendered list width.

### GREEN

Focused divider verification after implementation:

```text
.venv/bin/python -m pytest tests/test_ui_candidates.py -k "divider" -q
4 passed, 21 deselected in 0.06s
```

The maximum left track now uses the workbench `clientWidth`, leaving exactly
the divider width plus the 480-pixel detail track inside the content box.
Pointer coordinates still use `event.clientX - rect.left`. The script records
an explicit `userAdjusted` state only after pointer or keyboard resizing.
Before that state exists, desktop synchronization removes any inline width and
uses the CSS 22% default, including after a mobile-first load. Once adjusted,
the page-local pixel width is preserved and clamped across responsive
transitions.

Final verification:

```text
.venv/bin/python -m pytest tests/test_ui_candidates.py -q
25 passed in 0.04s

.venv/bin/python -m pytest -q
130 passed in 2.72s

git diff --check
exit 0
```
