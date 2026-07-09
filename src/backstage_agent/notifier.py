from __future__ import annotations

import subprocess


def send_mac_notification(title: str, message: str) -> bool:
    script = f'display notification {_apple_quote(message)} with title {_apple_quote(title)}'
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "unknown osascript error").strip()
        print(f"Notification failed: {detail}")
        return False
    print("Notification sent.")
    return True


def _apple_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
