# Daily Scan Missing-Email Retry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retry the daily Backstage scan at 9/10/11/12 until `messages_seen > 0`, then stop for the day; after a final empty noon attempt, notify once and stop.

**Architecture:** launchd fires `scripts/daily_scan.sh` four times via calendar intervals. The shell script owns per-day state (`logs/daily-scan-state.json`), decides skip/retry/give-up from local hour + `messages_seen`, and owns notifications so empty retries stay silent. No Python CLI retry flags.

**Tech Stack:** zsh, macOS launchd plist, Python 3 JSON parsing helpers inside the shell script, pytest for script-behavior tests via env overrides.

## Global Constraints

- Missing-email means **`messages_seen == 0` only**.
- Attempts at **9:00, 10:00, 11:00, 12:00** local time (four total).
- Retry/log (no notify) when empty and local hour **`< 12`**; give-up + notify when empty and hour **`>= 12`**.
- Do not pass `--notify` on the scan CLI invocation; shell notifies only on success-with-messages or final miss (and hard failures).
- Candidate scoring must never be invoked by the daily script.
- State file lives under `logs/` (already gitignored).
- Keep changes limited to launchd plist, daily scan script, tests, and ops docs (`README.md`, `PROJECT_STATE.md`, `CHANGELOG.md`).

---

## File Structure

| File | Responsibility |
|---|---|
| `launchd/com.sarahtxy.backstage-agent.daily.plist` | Schedule 9/10/11/12 |
| `scripts/daily_scan.sh` | State gating, scan, retry/give-up, notifications, dashboard check |
| `tests/test_daily_scan_script.py` | Assert script contract + runnable behavior via env overrides |
| `README.md` | Document retry schedule and reload note |
| `PROJECT_STATE.md` / `CHANGELOG.md` | Reflect new automation behavior |

---

### Task 1: Make daily scan script testable and enforce retry contract

**Files:**
- Modify: `scripts/daily_scan.sh`
- Modify: `tests/test_daily_scan_script.py`
- Modify: `launchd/com.sarahtxy.backstage-agent.daily.plist`
- Modify: `README.md`, `PROJECT_STATE.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: CLI scan JSON with integer `messages_seen` and string `summary`
- Produces: `logs/daily-scan-state.json` with keys `date`, `status` (`pending` \| `succeeded` \| `gave_up`), `last_attempt_at`, `messages_seen`
- Env overrides for tests:
  - `DAILY_SCAN_PROJECT_DIR` (default: hardcoded project path, or script dir parent if overridden)
  - `DAILY_SCAN_STATE_FILE`
  - `DAILY_SCAN_DATE` (`YYYY-MM-DD`)
  - `DAILY_SCAN_HOUR` (`0`-`23`, unpadded or zero-padded integer)
  - `DAILY_SCAN_PYTHON` (python used to run scan)
  - `DAILY_SCAN_NOTIFY_CMD` (optional; default `/usr/bin/osascript`; tests can point at a recorder script)

- [ ] **Step 1: Rewrite the failing/updated tests first**

Replace `tests/test_daily_scan_script.py` with:

```python
from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "daily_scan.sh"
PLIST = REPO / "launchd" / "com.sarahtxy.backstage-agent.daily.plist"


def test_daily_scan_runs_selection_without_scoring_or_cli_notify():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "backstage_agent.cli scan --days 1 --limit 25" in script
    assert "scan --days 1 --limit 25 --notify" not in script
    assert "score-candidates" not in script
    assert "rescore-candidates" not in script
    assert "daily-scan-state.json" in script


def test_plist_schedules_four_hourly_attempts():
    text = PLIST.read_text(encoding="utf-8")
    assert text.count("<key>Hour</key>") == 4
    for hour in (9, 10, 11, 12):
        assert f"<integer>{hour}</integer>" in text


def _write_executable(path: Path, contents: str) -> None:
    path.write_text(contents, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_daily_scan(
    tmp_path: Path,
    *,
    hour: int,
    day: str,
    messages_seen: int,
    preexisting_state: dict | None = None,
    scan_exit: int = 0,
) -> subprocess.CompletedProcess[str]:
    project_dir = tmp_path / "project"
    logs = project_dir / "logs"
    logs.mkdir(parents=True)
    state_file = logs / "daily-scan-state.json"
    if preexisting_state is not None:
        state_file.write_text(json.dumps(preexisting_state), encoding="utf-8")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_stub = bin_dir / "python"
    notify_log = tmp_path / "notify.log"
    notify_stub = bin_dir / "notify"
    summary = f"stub summary messages={messages_seen}"
    payload = json.dumps({"messages_seen": messages_seen, "summary": summary}, indent=2)
    _write_executable(
        python_stub,
        textwrap.dedent(
            f"""\
            #!/bin/zsh
            echo '{payload}'
            exit {scan_exit}
            """
        ),
    )
    _write_executable(
        notify_stub,
        textwrap.dedent(
            f"""\
            #!/bin/zsh
            echo "$@" >> "{notify_log}"
            exit 0
            """
        ),
    )

    env = os.environ.copy()
    env.update(
        {
            "DAILY_SCAN_PROJECT_DIR": str(project_dir),
            "DAILY_SCAN_STATE_FILE": str(state_file),
            "DAILY_SCAN_DATE": day,
            "DAILY_SCAN_HOUR": str(hour),
            "DAILY_SCAN_PYTHON": str(python_stub),
            "DAILY_SCAN_NOTIFY_CMD": str(notify_stub),
        }
    )
    return subprocess.run(
        ["/bin/zsh", str(SCRIPT)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_skips_when_already_succeeded(tmp_path: Path):
    result = _run_daily_scan(
        tmp_path,
        hour=10,
        day="2026-07-18",
        messages_seen=5,
        preexisting_state={
            "date": "2026-07-18",
            "status": "succeeded",
            "last_attempt_at": "2026-07-18T09:00:00",
            "messages_seen": 1,
        },
    )
    assert result.returncode == 0
    notify_log = tmp_path / "notify.log"
    assert not notify_log.exists()


def test_empty_before_noon_exits_zero_without_notify(tmp_path: Path):
    result = _run_daily_scan(tmp_path, hour=9, day="2026-07-18", messages_seen=0)
    assert result.returncode == 0
    state = json.loads((tmp_path / "project" / "logs" / "daily-scan-state.json").read_text())
    assert state["status"] == "pending"
    assert state["messages_seen"] == 0
    assert not (tmp_path / "notify.log").exists()


def test_empty_at_noon_gives_up_and_notifies(tmp_path: Path):
    result = _run_daily_scan(tmp_path, hour=12, day="2026-07-18", messages_seen=0)
    assert result.returncode == 0
    state = json.loads((tmp_path / "project" / "logs" / "daily-scan-state.json").read_text())
    assert state["status"] == "gave_up"
    notify_text = (tmp_path / "notify.log").read_text()
    assert "No Backstage email today" in notify_text or "no Backstage email" in notify_text.lower()


def test_messages_seen_marks_succeeded_and_notifies(tmp_path: Path):
    # Dashboard check would fail in temp project; stub ensure_dashboard by placing a no-op script.
    project_dir = tmp_path / "project"
    scripts = project_dir / "scripts"
    scripts.mkdir(parents=True)
    _write_executable(scripts / "ensure_dashboard.sh", "#!/bin/zsh\nexit 0\n")

    result = _run_daily_scan(tmp_path, hour=9, day="2026-07-18", messages_seen=2)
    assert result.returncode == 0
    state = json.loads((project_dir / "logs" / "daily-scan-state.json").read_text())
    assert state["status"] == "succeeded"
    assert state["messages_seen"] == 2
    notify_text = (tmp_path / "notify.log").read_text()
    assert "Backstage Agent done" in notify_text
```

Note: the success-path test needs the script to call `$PROJECT_DIR/scripts/ensure_dashboard.sh`. Keep that path. If the current script hardcodes `/Users/sarahtxy/dev/backstage_agent`, switch it to `DAILY_SCAN_PROJECT_DIR` with that absolute path as default.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_daily_scan_script.py -v`

Expected: FAIL (old script still has `--notify`, plist still one hour, runtime tests fail).

- [ ] **Step 3: Update the launchd plist to four hours**

Replace the single `StartCalendarInterval` dict in `launchd/com.sarahtxy.backstage-agent.daily.plist` with an array of four dicts:

```xml
  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>9</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>10</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>11</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>12</integer>
      <key>Minute</key>
      <integer>0</integer>
    </dict>
  </array>
```

Keep `Label`, `ProgramArguments`, and log paths unchanged.

- [ ] **Step 4: Rewrite `scripts/daily_scan.sh`**

Implement this full script (preserve zsh + `set -euo pipefail`):

```zsh
#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${DAILY_SCAN_PROJECT_DIR:-/Users/sarahtxy/dev/backstage_agent}"
cd "$PROJECT_DIR"

mkdir -p logs

STATE_FILE="${DAILY_SCAN_STATE_FILE:-$PROJECT_DIR/logs/daily-scan-state.json}"
TODAY="${DAILY_SCAN_DATE:-$(/bin/date '+%Y-%m-%d')}"
HOUR="${DAILY_SCAN_HOUR:-$(/bin/date '+%-H' 2>/dev/null || /bin/date '+%H')}"
# Normalize zero-padded hour (e.g. 09 -> 9) for numeric compares.
HOUR=$((10#$HOUR))
PYTHON="${DAILY_SCAN_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
NOTIFY_CMD="${DAILY_SCAN_NOTIFY_CMD:-/usr/bin/osascript}"
OUT_LOG="$PROJECT_DIR/logs/daily-scan.out.log"
ERR_LOG="$PROJECT_DIR/logs/daily-scan.err.log"

notify() {
  local title="$1"
  local message="$2"
  if [[ "$NOTIFY_CMD" == "/usr/bin/osascript" ]]; then
    "$NOTIFY_CMD" -e "display notification \"$message\" with title \"$title\"" >/dev/null 2>&1 || true
  else
    "$NOTIFY_CMD" "$title" "$message" >/dev/null 2>&1 || true
  fi
}

read_state_status() {
  if [[ ! -f "$STATE_FILE" ]]; then
    echo ""
    return
  fi
  "$PYTHON" - "$STATE_FILE" "$TODAY" <<'PY'
import json, sys
path, today = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    print("")
    raise SystemExit(0)
if data.get("date") != today:
    print("")
else:
    print(data.get("status") or "")
PY
}

write_state() {
  local status="$1"
  local messages_seen="$2"
  local stamp
  stamp="$(/bin/date '+%Y-%m-%dT%H:%M:%S%z')"
  "$PYTHON" - "$STATE_FILE" "$TODAY" "$status" "$messages_seen" "$stamp" <<'PY'
import json, sys
path, today, status, messages_seen, stamp = sys.argv[1:6]
payload = {
    "date": today,
    "status": status,
    "last_attempt_at": stamp,
    "messages_seen": int(messages_seen),
}
with open(path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
    handle.write("\n")
PY
}

{
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Starting daily Backstage scan (hour=$HOUR date=$TODAY)"

  existing_status="$(read_state_status)"
  if [[ "$existing_status" == "succeeded" || "$existing_status" == "gave_up" ]]; then
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Skipping: already $existing_status for $TODAY"
    exit 0
  fi

  scan_out="$(mktemp)"
  if ! "$PYTHON" -m backstage_agent.cli scan --days 1 --limit 25 >"$scan_out" 2>>"$ERR_LOG"; then
    notify "Backstage Agent failed" "Open logs/daily-scan.err.log for details."
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Daily Backstage scan failed"
    rm -f "$scan_out"
    exit 1
  fi
  cat "$scan_out"

  messages_seen="$("$PYTHON" - "$scan_out" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(int(data.get("messages_seen") or 0))
PY
)"
  summary="$("$PYTHON" - "$scan_out" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(data.get("summary") or "Backstage scan finished")
PY
)"
  rm -f "$scan_out"

  if (( messages_seen > 0 )); then
    write_state "succeeded" "$messages_seen"
    notify "Backstage Agent done" "$summary"
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Finished daily Backstage scan (messages_seen=$messages_seen)"
    if "$PROJECT_DIR/scripts/ensure_dashboard.sh"; then
      echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Dashboard health check passed"
    else
      notify "Backstage dashboard failed" "Open logs/daily-scan.err.log for details."
      echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Dashboard health check failed"
      exit 1
    fi
    exit 0
  fi

  if (( HOUR < 12 )); then
    write_state "pending" 0
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Empty inbox (messages_seen=0); will retry later"
    exit 0
  fi

  write_state "gave_up" 0
  notify "Backstage Agent" "No Backstage email today"
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Gave up for $TODAY: no Backstage email"
  exit 0
} >>"$OUT_LOG" 2>>"$ERR_LOG"
```

Implementation notes:
- On macOS, `date '+%-H'` may not exist on all BSD date variants; the `||-H` fallback above handles that. Prefer `date '+%H'` then `HOUR=$((10#$HOUR))`.
- For production notify titles/messages, keep failure copy close to today's script.
- Success-path tests create `$PROJECT_DIR/scripts/ensure_dashboard.sh`; production uses the real one.

- [ ] **Step 5: Fix the success-path test harness if needed**

If Step 4's script always uses `$PROJECT_DIR/scripts/ensure_dashboard.sh`, the success test must create that stub **before** calling `_run_daily_scan`, or `_run_daily_scan` should create a default passing stub. Prefer updating `_run_daily_scan` to always install a no-op `ensure_dashboard.sh` unless `dashboard_exit` is provided.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_daily_scan_script.py -v`

Expected: all PASS.

- [ ] **Step 7: Update docs**

In `README.md` Daily Automation section, replace the single-run description with:

- launchd runs at 9:00, 10:00, 11:00, and 12:00 local time
- if `messages_seen == 0` before noon, the job exits quietly and retries next hour
- if still empty at noon, notify “No Backstage email today” and stop
- after a successful scan for the day, later hours no-op
- scan command used by the script no longer passes `--notify` (shell notifies)
- remind to reload launchd after plist changes, e.g.:

```bash
launchctl bootout gui/$(id -u)/com.sarahtxy.backstage-agent.daily 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$PWD/launchd/com.sarahtxy.backstage-agent.daily.plist"
```

(Use the reload commands already documented in the repo if present; otherwise the above.)

Update `PROJECT_STATE.md` daily automation bullet to mention 9–12 missing-email retries.

Add a concise `CHANGELOG.md` entry under the latest date section (or today's date) describing the retry behavior.

- [ ] **Step 8: Commit**

```bash
git add \
  scripts/daily_scan.sh \
  launchd/com.sarahtxy.backstage-agent.daily.plist \
  tests/test_daily_scan_script.py \
  README.md \
  PROJECT_STATE.md \
  CHANGELOG.md
git commit -m "$(cat <<'EOF'
feat: retry daily scan until Backstage email arrives

Schedule 9–12 launchd attempts and gate retries on messages_seen with
a per-day state file, notifying only on success or final noon miss.
EOF
)"
```

---

### Task 2: Operator reload note verification (manual)

**Files:**
- None (ops check only)

**Interfaces:**
- Consumes: updated plist from Task 1
- Produces: confirmation that launchd will fire four times

- [ ] **Step 1: Inspect installed/loaded job definition**

After the user reloads (or in dry inspection of the repo plist):

```bash
plutil -p launchd/com.sarahtxy.backstage-agent.daily.plist | rg -n "Hour|Minute|StartCalendar"
```

Expected: hours 9, 10, 11, 12 each with minute 0.

- [ ] **Step 2: Reminder only — do not auto-reload without asking**

Tell the user they must reload the launch agent for the new schedule to take effect. Do not run `launchctl bootstrap/bootout` unless they explicitly ask.

- [ ] **Step 3: No commit** (docs already committed in Task 1)

---

## Self-Review vs Spec

| Spec requirement | Task |
|---|---|
| 9/10/11/12 schedule | Task 1 plist + tests |
| `messages_seen == 0` retry trigger | Task 1 script + tests |
| hour `< 12` retry, `>= 12` give up | Task 1 script + tests |
| skip after succeeded/gave_up | Task 1 script + tests |
| notify success-with-messages and final miss only | Task 1 script + tests |
| no CLI `--notify` on empty path | Task 1 script + tests |
| no scoring in daily job | Task 1 static assert |
| docs + changelog | Task 1 |
| reload note | Task 1 docs + Task 2 |

No placeholders remain. Env override names are consistent across tests and script.
