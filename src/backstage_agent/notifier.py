from __future__ import annotations

import subprocess


def send_mac_notification(title: str, message: str) -> None:
    script = f'display notification {_apple_quote(message)} with title {_apple_quote(title)}'
    subprocess.run(
        ["/usr/bin/osascript", "-e", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _apple_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
