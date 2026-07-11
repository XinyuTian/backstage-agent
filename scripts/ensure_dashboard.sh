#!/bin/zsh
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/Users/sarahtxy/dev/backstage_agent}"
DASHBOARD_LABEL="com.sarahtxy.backstage-agent.ui"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:8765/}"
PLIST_SOURCE="$PROJECT_DIR/launchd/$DASHBOARD_LABEL.plist"
PLIST_TARGET="$HOME/Library/LaunchAgents/$DASHBOARD_LABEL.plist"
USER_DOMAIN="gui/$(/usr/bin/id -u)"
SERVICE="$USER_DOMAIN/$DASHBOARD_LABEL"

dashboard_alive() {
  /usr/bin/curl -fs --max-time 3 "$DASHBOARD_URL" >/dev/null
}

restart_dashboard() {
  if [[ ! -f "$PLIST_SOURCE" ]]; then
    echo "Dashboard LaunchAgent plist missing: $PLIST_SOURCE"
    return 1
  fi

  /bin/mkdir -p "$HOME/Library/LaunchAgents"
  /bin/cp "$PLIST_SOURCE" "$PLIST_TARGET"

  /bin/launchctl bootout "$SERVICE" >/dev/null 2>&1 || true
  /bin/launchctl bootstrap "$USER_DOMAIN" "$PLIST_TARGET"
  /bin/launchctl enable "$SERVICE"
  /bin/launchctl kickstart -k "$SERVICE"
}

if dashboard_alive; then
  echo "Dashboard healthy at $DASHBOARD_URL"
  exit 0
fi

echo "Dashboard is not responding at $DASHBOARD_URL; restarting LaunchAgent"
restart_dashboard

/bin/sleep 2

if dashboard_alive; then
  echo "Dashboard restored at $DASHBOARD_URL"
  exit 0
fi

echo "Dashboard still not responding after restart"
exit 1
