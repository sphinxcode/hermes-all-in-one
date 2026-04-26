from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from urllib.error import URLError
from urllib.request import urlopen

from control_plane.config import (
    HERMES_CONFIG_PATH,
    HERMES_HOME,
    HOME_DIR,
    INTERNAL_DASHBOARD_BASE,
    INTERNAL_DASHBOARD_HOST,
    INTERNAL_DASHBOARD_PORT,
)


class DashboardManager:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.logs: deque[str] = deque(maxlen=500)
        self.start_time: float | None = None
        self._lock = threading.Lock()

    def _capture_stream(self, stream) -> None:
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            self.logs.append(line.rstrip())
        try:
            stream.close()
        except OSError:
            pass

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.is_running():
                return
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(HOME_DIR),
                    "HERMES_HOME": str(HERMES_HOME),
                    "HERMES_CONFIG_PATH": str(HERMES_CONFIG_PATH),
                    "PYTHONUNBUFFERED": "1",
                }
            )
            self.process = subprocess.Popen(
                [
                    "hermes",
                    "dashboard",
                    "--host",
                    INTERNAL_DASHBOARD_HOST,
                    "--port",
                    str(INTERNAL_DASHBOARD_PORT),
                    "--no-open",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )
            self.start_time = time.time()
            threading.Thread(target=self._capture_stream, args=(self.process.stdout,), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            if not self.is_running():
                return
            assert self.process is not None
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def restart(self) -> None:
        self.stop()
        self.start()

    def wait_until_ready(self, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.health_ok():
                return True
            if self.process and self.process.poll() is not None:
                return False
            time.sleep(0.5)
        return False

    def health_ok(self) -> bool:
        try:
            with urlopen(f"{INTERNAL_DASHBOARD_BASE}/api/status", timeout=2) as response:
                return 200 <= response.status < 300
        except URLError:
            return False
        except Exception:
            return False

    def status(self) -> dict:
        pid = self.process.pid if self.process else None
        return {
            "running": self.is_running(),
            "pid": pid,
            "uptime_seconds": int(time.time() - self.start_time) if self.start_time and self.is_running() else 0,
            "healthy": self.health_ok(),
            "internal_base_url": INTERNAL_DASHBOARD_BASE,
            "log_tail": list(self.logs)[-50:],
        }
