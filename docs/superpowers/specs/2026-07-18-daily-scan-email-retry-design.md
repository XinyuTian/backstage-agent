# Daily Scan Missing-Email Retry Design

Date: 2026-07-18

## Problem

The daily Backstage scan runs once at 9:00 local time via launchd. The casting notification email sometimes arrives later. When the 9am run finds no matching messages, the day is effectively skipped unless the user reruns manually.

## Goal

Retry the daily scan until today's Backstage email appears, then stop for the day. If it never appears by the final attempt, notify once and stop.

## Requirements

- Initial attempt at **9:00**; retries at **10:00, 11:00, and 12:00** (four attempts total).
- Treat "email missing" as **`messages_seen == 0`** only.
- Do **not** treat CLI/script failures as missing-email retries.
- Skip later hourly runs after a successful scan for that local date.
- macOS notifications:
  - on successful scan with messages (existing success path)
  - once after the noon attempt if still `messages_seen == 0` ("no Backstage email today")
  - not on empty attempts at 9/10/11
  - on real failures (existing failure path)
- Keep candidate scoring out of the daily job (unchanged).

## Approach

Use launchd calendar intervals at 9/10/11/12 and put retry/stop logic in `scripts/daily_scan.sh`, gated by a small per-day state file. Do not add an in-process sleep loop or new Python CLI retry flags.

## Schedule

`launchd/com.sarahtxy.backstage-agent.daily.plist` uses four `StartCalendarInterval` entries:

| Local time | Role |
|---|---|
| 09:00 | Initial attempt |
| 10:00 | Retry 1 |
| 11:00 | Retry 2 |
| 12:00 | Retry 3 (final) |

After changing the plist, reload the launchd job so macOS picks up the new hours.

## Control flow

Each hourly run of `scripts/daily_scan.sh`:

1. Ensure `logs/` exists.
2. Read `logs/daily-scan-state.json`.
3. If state `date` is today's local date and `status` is `succeeded` or `gave_up` → exit 0 quietly (no scan, no notify).
4. Otherwise run today's scan with `--days 1 --limit 25`, capturing JSON stdout. Do **not** pass `--notify` on this invocation; the shell owns notifications after inspecting the result so empty retries stay silent.
5. If the CLI exits non-zero → existing failure notification + log; exit non-zero. Do not update status to `succeeded` or `gave_up` based on "missing email".
6. Parse `messages_seen` from the JSON summary.
7. If `messages_seen > 0`:
   - write state `{ date: today, status: "succeeded", ... }`
   - send the existing-style success notification from the shell (equivalent to today's `--notify` summary)
   - run dashboard health check as today
   - exit according to dashboard check result
8. If `messages_seen == 0` and local hour **&lt; 12** (9, 10, or 11):
   - write/update state for today as still pending (or leave pending), record last attempt
   - log that the inbox was empty and a later retry will run
   - exit 0 (not a failure; no user notification)
9. If `messages_seen == 0` and local hour **≥ 12** (noon final attempt, including slightly late fires):
   - write state `{ date: today, status: "gave_up", ... }`
   - notify that there was no Backstage email today
   - exit 0

Hour boundary rationale: retries at 9/10/11 use `hour < 12`; noon and later use `hour >= 12` so a slightly delayed noon fire still gives up instead of claiming another retry will happen.

## State file

Path: `logs/daily-scan-state.json`  
Already covered by `.gitignore` entry for `logs/`.

Example:

```json
{
  "date": "2026-07-18",
  "status": "pending",
  "last_attempt_at": "2026-07-18T11:00:03-07:00",
  "messages_seen": 0
}
```

Allowed `status` values:

- `pending` — today not yet succeeded or given up
- `succeeded` — at least one matching message was seen and the scan completed that path
- `gave_up` — noon attempt still saw zero messages

State is keyed by local calendar `date`. A new day starts fresh.

## Notifications

| Event | Notify? |
|---|---|
| Empty at 9/10/11 | No |
| Empty at noon (final) | Yes — no Backstage email today |
| Scan found messages and finished success path | Yes — existing success notify |
| CLI or dashboard hard failure | Yes — existing failure notify |

## Out of scope

- Python-level retry loops or new `scan` CLI flags
- Changing screening, scoring, storage, or dashboard product logic
- Retrying because projects/notices are empty while `messages_seen > 0`
- Keeping a long-lived process asleep between hours

## Files to change

- `launchd/com.sarahtxy.backstage-agent.daily.plist`
- `scripts/daily_scan.sh`
- `README.md` (daily automation section)
- `PROJECT_STATE.md` and `CHANGELOG.md` when implementing

## Testing / verification

- Script-level checks for: skip when already succeeded; retry logging when empty before noon; give-up notify at noon; no give-up notify before noon.
- Manual verification after reload: confirm launchd shows four calendar intervals.
- Do not require live IMAP for unit-style script tests; use fixture JSON / stubbed scan invocation where practical.

## Success criteria

- If the email arrives by noon, exactly one successful daily scan runs that day for the automation path, and later hours no-op.
- If it never arrives, the user gets one final miss notification after the noon attempt and no further automation scans that day.
- Real errors remain distinguishable from "email not here yet."
