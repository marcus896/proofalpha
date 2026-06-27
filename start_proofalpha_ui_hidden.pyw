from __future__ import annotations

import os
import re
import subprocess
import sys
import time
import webbrowser
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PID_FILE = ROOT / ".proofalpha_ui_server.pid"
RUN_SCRIPT = ROOT / "ui_server.py"
URL = "http://localhost:8080/dashboard.html"


def _python_path() -> str:
    executable = Path(sys.executable)
    if executable.name.lower() == "python.exe":
        return str(executable)
    candidate = executable.with_name("python.exe")
    if candidate.exists():
        return str(candidate)
    return str(executable)


def _is_our_server_process(pid: int) -> bool:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
        text=True,
    )
    command_line = completed.stdout or ""
    return "ui_server.py" in command_line and str(ROOT) in command_line


def _kill_existing_server() -> None:
    netstat = subprocess.run(
        ["netstat", "-ano"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
        text=True,
    )
    port_pattern = re.compile(r"^\s*TCP\s+127\.0\.0\.1:8080\s+\S+\s+LISTENING\s+(\d+)\s*$", re.MULTILINE)
    pids = {
        pid
        for pid in (int(match.group(1)) for match in port_pattern.finditer(netstat.stdout or ""))
        if _is_our_server_process(pid)
    }

    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pid = None
        if pid is not None and _is_our_server_process(pid):
            pids.add(pid)

    for active_pid in sorted(pids):
        subprocess.run(
            ["taskkill", "/PID", str(active_pid), "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    PID_FILE.unlink(missing_ok=True)


def _start_server() -> int:
    creationflags = 0
    for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
        creationflags |= getattr(subprocess, flag_name, 0)

    process = subprocess.Popen(
        [_python_path(), str(RUN_SCRIPT)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    return process.pid


def main() -> None:
    os.chdir(ROOT)
    _kill_existing_server()
    _start_server()
    time.sleep(1.4)
    webbrowser.open(URL)


if __name__ == "__main__":
    main()
