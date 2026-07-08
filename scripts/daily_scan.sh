#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/sarahtxy/dev/backstage_agent"
cd "$PROJECT_DIR"

mkdir -p logs

{
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Starting daily Backstage scan"
  if "$PROJECT_DIR/.venv/bin/python" -m backstage_agent.cli scan --days 1 --limit 25 --notify; then
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Finished daily Backstage scan"
  else
    /usr/bin/osascript -e 'display notification "Open logs/daily-scan.err.log for details." with title "Backstage Agent failed"' >/dev/null 2>&1 || true
    echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Daily Backstage scan failed"
    exit 1
  fi
} >> "$PROJECT_DIR/logs/daily-scan.out.log" 2>> "$PROJECT_DIR/logs/daily-scan.err.log"
