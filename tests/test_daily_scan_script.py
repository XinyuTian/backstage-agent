from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

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
    messages_seen: int | None = 0,
    preexisting_state: dict | None = None,
    scan_exit: int = 0,
    scan_payload: dict | str | None = None,
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
    if scan_payload is None:
        summary = f"stub summary messages={messages_seen}"
        payload = json.dumps({"messages_seen": messages_seen, "summary": summary}, indent=2)
    elif isinstance(scan_payload, dict):
        payload = json.dumps(scan_payload, indent=2)
    else:
        payload = scan_payload
    real_python = REPO / ".venv" / "bin" / "python"
    _write_executable(
        python_stub,
        textwrap.dedent(
            f"""\
            #!/bin/zsh
            if [[ "$1" == "-m" && "$2" == "backstage_agent.cli" ]]; then
              echo '{payload}'
              exit {scan_exit}
            fi
            exec {real_python} "$@"
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

    scripts = project_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    _write_executable(scripts / "ensure_dashboard.sh", "#!/bin/zsh\nexit 0\n")

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


def test_skips_when_already_gave_up(tmp_path: Path):
    result = _run_daily_scan(
        tmp_path,
        hour=10,
        day="2026-07-18",
        messages_seen=0,
        preexisting_state={
            "date": "2026-07-18",
            "status": "gave_up",
            "last_attempt_at": "2026-07-18T12:00:00",
            "messages_seen": 0,
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
    result = _run_daily_scan(tmp_path, hour=9, day="2026-07-18", messages_seen=2)
    assert result.returncode == 0
    state = json.loads((tmp_path / "project" / "logs" / "daily-scan-state.json").read_text())
    assert state["status"] == "succeeded"
    assert state["messages_seen"] == 2
    notify_text = (tmp_path / "notify.log").read_text()
    assert "Backstage Agent done" in notify_text


def _assert_hard_failure(result: subprocess.CompletedProcess[str], tmp_path: Path) -> None:
    assert result.returncode != 0
    notify_text = (tmp_path / "notify.log").read_text()
    assert "Backstage Agent failed" in notify_text
    state_file = tmp_path / "project" / "logs" / "daily-scan-state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        assert state.get("status") not in {"succeeded", "gave_up"}


@pytest.mark.parametrize(
    "scan_payload",
    [
        {"summary": "no messages_seen key"},
        {"messages_seen": None, "summary": "null"},
        {"messages_seen": "0", "summary": "string zero"},
        {"messages_seen": -1, "summary": "negative"},
    ],
)
def test_invalid_messages_seen_hard_fails(tmp_path: Path, scan_payload: dict):
    result = _run_daily_scan(
        tmp_path,
        hour=9,
        day="2026-07-18",
        scan_payload=scan_payload,
    )
    _assert_hard_failure(result, tmp_path)


def test_malformed_scan_json_hard_fails(tmp_path: Path):
    result = _run_daily_scan(
        tmp_path,
        hour=9,
        day="2026-07-18",
        scan_payload="{not valid json",
    )
    _assert_hard_failure(result, tmp_path)


def test_cli_scan_failure_notifies(tmp_path: Path):
    result = _run_daily_scan(
        tmp_path,
        hour=9,
        day="2026-07-18",
        messages_seen=2,
        scan_exit=1,
    )
    _assert_hard_failure(result, tmp_path)
