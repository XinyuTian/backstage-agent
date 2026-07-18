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
  local next_status="$1"
  local messages_seen="$2"
  local stamp
  stamp="$(/bin/date '+%Y-%m-%dT%H:%M:%S%z')"
  "$PYTHON" - "$STATE_FILE" "$TODAY" "$next_status" "$messages_seen" "$stamp" <<'PY'
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

  if ! messages_seen="$("$PYTHON" - "$scan_out" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    raise SystemExit(2)
if "messages_seen" not in data:
    raise SystemExit(2)
value = data["messages_seen"]
if not isinstance(value, int) or isinstance(value, bool):
    raise SystemExit(2)
if value < 0:
    raise SystemExit(2)
print(value)
PY
)"; then
    notify "Backstage Agent failed" "Open logs/daily-scan.err.log for details."
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Daily Backstage scan failed: invalid scan output"
    rm -f "$scan_out"
    exit 1
  fi

  summary="$("$PYTHON" - "$scan_out" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
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
