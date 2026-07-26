# Date Navigation Button Polish

## Scope

- Give `Today`, previous day, next day, and `7 days` the same filled green visual treatment as `Filter`.
- Render the day navigation labels as literal `<` and `>` while retaining the existing URLs and `Previous day` / `Next day` aria labels.

## RED evidence

Command:

`.venv/bin/python -m pytest tests/test_ui_candidates.py -k date_navigation_uses_filter_button_style_and_literal_arrow_text -q`

Result: `1 failed, 20 deselected`

Expected failure:

`assert 'aria-label="Previous day">&lt;</a>' in html`

The existing renderer still emitted the Unicode left arrow and only styled the active seven-day control.

## GREEN evidence

Focused command:

`.venv/bin/python -m pytest tests/test_ui_candidates.py -q`

Result: `21 passed in 0.04s`

Full-suite command:

`.venv/bin/python -m pytest -q`

Result: `126 passed in 3.17s`

## Implementation

- Kept all four links on the shared `date-nav` class.
- Shared Filter's filled green color contract through `button, .date-nav`.
- Added matching border, radius, padding, font, and link-decoration rules for date-navigation anchors.
- Preserved `aria-pressed` on the seven-day toggle and both day-navigation aria labels.
- Preserved all existing query, date, band, and day-window URL behavior.
