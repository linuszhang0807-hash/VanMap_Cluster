"""
Task runner — reads master_hermes/order_box/task.json and executes commands.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ORDER_BOX = Path(__file__).resolve().parent / "order_box"
TASK_FILE = ORDER_BOX / "task.json"
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRAPER_DIR = REPO_ROOT / "slave_scraper"


def _read_task() -> dict:
    with open(TASK_FILE, encoding="utf-8") as f:
        return json.load(f)


def _write_status(status: str, *, detail: str = "") -> None:
    task = _read_task()
    task["status"] = status
    task["updated_at"] = datetime.now(timezone.utc).isoformat()
    if detail:
        task["detail"] = detail
    with open(TASK_FILE, "w", encoding="utf-8") as f:
        json.dump(task, f, ensure_ascii=False, indent=2)


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    result = subprocess.run(
        cmd,
        cwd=str(cwd or REPO_ROOT),
        capture_output=True,
        text=True,
    )
    out = (result.stdout or "") + (result.stderr or "")
    return result.returncode, out


def execute_task() -> int:
    if not TASK_FILE.exists():
        print("[task_runner] No task.json found")
        return 1

    task = _read_task()
    command = task.get("command", "")
    print(f"[task_runner] Executing command: {command}")

    _write_status("RUNNING")

    try:
        if command == "RUN_EVENTS_SCRAPER":
            code, out = _run([sys.executable, "events_scraper.py", "--sync"], cwd=SCRAPER_DIR)
        elif command == "RUN_PLACE_SCRAPER":
            code, out = _run([sys.executable, "vancouver_scraper.py", "--sync"], cwd=SCRAPER_DIR)
        elif command == "SYNC_DATA":
            sync_ps1 = REPO_ROOT / "scripts" / "sync_data.ps1"
            sync_sh = REPO_ROOT / "scripts" / "sync_data.sh"
            if sys.platform == "win32" and sync_ps1.exists():
                code, out = _run(["powershell", "-File", str(sync_ps1)])
            elif sync_sh.exists():
                code, out = _run(["bash", str(sync_sh)])
            else:
                code, out = 1, "sync script not found"
        elif command == "FULL_REFRESH":
            code1, out1 = _run([sys.executable, "vancouver_scraper.py"], cwd=SCRAPER_DIR)
            code2, out2 = _run([sys.executable, "events_scraper.py", "--sync"], cwd=SCRAPER_DIR)
            code, out = (code1 or code2), out1 + out2
        elif command == "CREATE_MAP_FRAMEWORK":
            code, out = 0, "Map framework already exists in slave_coder/src"
        else:
            code, out = 1, f"Unknown command: {command}"

        if code == 0:
            _write_status("DONE", detail=out[-500:] if out else "ok")
            print("[task_runner] DONE")
            return 0

        _write_status("FAILED", detail=out[-800:] if out else f"exit {code}")
        print(f"[task_runner] FAILED:\n{out}")
        return code

    except Exception as exc:
        _write_status("FAILED", detail=str(exc))
        print(f"[task_runner] FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(execute_task())
