"""Менеджер фоновой задачи (одна в единицу времени).

Запускает `python -m kp2imdb <cmd>` как subprocess, захватывает stdout+stderr
построчно в буфер. Поддерживает отправку stdin (для "нажми Enter после логина")
и принудительную остановку.

ANSI-коды из rich/typer чистим, чтобы в браузере не было мусора.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


@dataclass
class LogLine:
    idx: int
    ts: float
    text: str


@dataclass
class TaskState:
    name: str = "idle"
    running: bool = False
    waiting_for_input: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    logs: list[LogLine] = field(default_factory=list)

    def append(self, text: str) -> None:
        self.logs.append(LogLine(idx=len(self.logs), ts=time.time(), text=text))

    def logs_since(self, after_idx: int) -> list[LogLine]:
        return [ln for ln in self.logs if ln.idx > after_idx]


WAITING_MARKERS = (
    "Нажми Enter",
    "пройди её",
    "капчу",
)


class TaskRunner:
    """Синглтон-менеджер единственной активной задачи."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root
        self.state = TaskState()
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def is_running(self) -> bool:
        return self.state.running and self._proc is not None and self._proc.poll() is None

    def start(self, subcommand: str) -> tuple[bool, str]:
        with self._lock:
            if self.is_running():
                return False, f"Уже выполняется: {self.state.name}"

            self.state = TaskState(
                name=subcommand,
                running=True,
                started_at=time.time(),
            )
            self.state.append(f"$ python -m kp2imdb {subcommand}")

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            env["PYTHONIOENCODING"] = "utf-8"
            env["NO_COLOR"] = "1"
            env["TERM"] = "dumb"

            self._proc = subprocess.Popen(
                [sys.executable, "-m", "kp2imdb", subcommand],
                cwd=str(self.project_root),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                text=True,
                env=env,
            )

            threading.Thread(target=self._reader, daemon=True).start()
            return True, "started"

    def _reader(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            for raw in iter(self._proc.stdout.readline, ""):
                line = _strip_ansi(raw.rstrip("\r\n"))
                if not line:
                    continue
                self.state.append(line)
                if any(m in line for m in WAITING_MARKERS):
                    self.state.waiting_for_input = True
        finally:
            self._proc.wait()
            self.state.exit_code = self._proc.returncode
            self.state.finished_at = time.time()
            self.state.running = False
            self.state.waiting_for_input = False
            self.state.append(
                f"--- завершено, exit code {self.state.exit_code} ---"
            )

    def send_enter(self) -> bool:
        if not self.is_running() or self._proc is None or self._proc.stdin is None:
            return False
        try:
            self._proc.stdin.write("\n")
            self._proc.stdin.flush()
            self.state.waiting_for_input = False
            self.state.append("> [отправлен Enter]")
            return True
        except (BrokenPipeError, OSError):
            return False

    def kill(self) -> bool:
        if not self.is_running() or self._proc is None:
            return False
        try:
            if sys.platform == "win32":
                self._proc.terminate()
            else:
                self._proc.send_signal(signal.SIGTERM)
            return True
        except OSError:
            return False
