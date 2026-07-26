# Adjustable Workbench Divider Design

Date: 2026-07-24

## Goal

Allow the candidate list and candidate detail panels to be resized horizontally
without adding persistent settings.

## Behavior

- The default desktop split is 22% candidate list and 78% candidate detail.
- A narrow visible divider sits between the two panels.
- Dragging the divider horizontally updates the panel split immediately.
- The candidate list cannot shrink below 220 pixels.
- The candidate detail cannot shrink below 480 pixels.
- The divider uses the horizontal resize cursor while hovered or dragged.
- The adjusted width is not stored; reloading restores the 22/78 default.

## Accessibility

- The divider is focusable and uses `role="separator"`.
- It exposes vertical orientation plus current, minimum, and maximum values.
- Left and right arrow keys adjust the split in small increments.
- Home restores the smallest allowed left panel.
- End restores the largest allowed left panel.

## Responsive Behavior

At the existing mobile breakpoint, the workbench remains stacked vertically.
The divider is hidden and resizing is disabled.

## Implementation

Keep the behavior inside the existing server-rendered `ui.py` HTML, CSS, and
JavaScript. Use a CSS custom property for the current left-panel width and
pointer events for dragging. Do not add storage, cookies, local storage,
dependencies, or schema changes.

## Testing

- Assert the rendered workbench contains an accessible separator.
- Assert the default CSS split is 22/78.
- Assert the JavaScript handles pointer drag and keyboard adjustment.
- Assert mobile CSS hides the divider.
- Run `tests/test_ui_candidates.py`, then the full test suite.
- Restart and verify the live dashboard divider visually and interactively.
