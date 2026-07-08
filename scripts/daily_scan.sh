#!/bin/zsh
set -euo pipefail

PROJECT_DIR="/Users/sarahtxy/Documents/backstage"
cd "$PROJECT_DIR"

mkdir -p logs

{
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Starting daily Backstage scan"
  "$PROJECT_DIR/.venv/bin/python" -m backstage_agent.cli scan --days 1 --limit 25
  echo "[$(/bin/date '+%Y-%m-%d %H:%M:%S %Z')] Finished daily Backstage scan"
} >> "$PROJECT_DIR/logs/daily-scan.out.log" 2>> "$PROJECT_DIR/logs/daily-scan.err.log"
