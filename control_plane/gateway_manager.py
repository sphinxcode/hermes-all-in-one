from __future__ import annotations

import os
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from control_plane.config import HERMES_CONFIG_PATH, HERMES_ENV_PATH, HERMES_HOME, HOME_DIR, load_env_file, should_autostart_gateway


class GatewayManager:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.logs: deque[str] = deque(maxlen=1000)
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
            env.update(load_env_file(HERMES_ENV_PATH))
            env.update(
                {
                    "HOME": str(HOME_DIR),
                    "HERMES_HOME": str(HERMES_HOME),
                    "HERMES_CONFIG_PATH": str(HERMES_CONFIG_PATH),
                    "PYTHONUNBUFFERED": "1",
                }
            )
            self.process = subprocess.Popen(
                ["hermes", "gateway"],
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

    def should_autostart(self) -> bool:
        return should_autostart_gateway(config_path=HERMES_CONFIG_PATH, env_path=HERMES_ENV_PATH)

    def health_ok(self) -> bool:
        """Gateway is healthy once its process has been alive for ≥3 s without exiting.
        hermes gateway is a messaging bot — it does not expose an HTTP health endpoint."""
        if not self.is_running():
            return False
        if self.start_time is None:
            return False
        return (time.time() - self.start_time) >= 3.0

    def status(self) -> dict:
        pid = self.process.pid if self.process else None
        return {
            "running": self.is_running(),
            "pid": pid,
            "uptime_seconds": int(time.time() - self.start_time) if self.start_time and self.is_running() else 0,
            "healthy": self.health_ok(),
            "autostart_eligible": self.should_autostart(),
            "log_tail": list(self.logs)[-100:],
        }
