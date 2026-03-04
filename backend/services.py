"""
services.py — Lifecycle management for backend services.

Managed services:
  - mac_api  : FastAPI application (uvicorn api:app --port 8000)
  - docker   : Docker Compose stack (MySQL :3307 + phpMyAdmin :8081)

Also provides a periodic DB health-check that attempts to connect to MySQL
and updates the `db_connection` status reported to the frontend.

Usage:
    mgr = ServicesManager(on_status_changed=my_callback, on_service_log=log_cb)
    mgr.start()      # starts background health-check thread
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from typing import Callable, Dict, Literal, Optional

logger = logging.getLogger("FlashBench.Services")

# Directory where api.py lives — used as cwd when spawning uvicorn
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

# ──────────────────────────────────────────────────
# Types (mirrors frontend ServicesStatus)
# ──────────────────────────────────────────────────

ServiceState   = Literal["running", "stopped", "starting", "stopping", "restarting"]
DbState        = Literal["connected", "disconnected", "checking"]
ApiHealthState = Literal["up", "down", "unknown"]

ServiceSource = Literal["dhcp", "nginx", "mac_api", "docker"]


class ServicesStatus:
    def __init__(self) -> None:
        self.mac_api:        ServiceState   = "stopped"
        self.docker:         ServiceState   = "stopped"
        self.db_connection:  DbState        = "disconnected"
        self.mac_api_health: ApiHealthState = "unknown"

    def to_dict(self) -> dict:
        return {
            "mac_api":        self.mac_api,
            "docker":         self.docker,
            "db_connection":  self.db_connection,
            "mac_api_health": self.mac_api_health,
        }


# ──────────────────────────────────────────────────
# Callbacks type aliases
# ──────────────────────────────────────────────────

StatusChangedCallback = Callable[[dict], None]
ServiceLogCallback    = Callable[[dict], None]  # {ts, level, message, source}


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────

def _make_log_entry(level: str, message: str, source: ServiceSource) -> dict:
    return {
        "ts":      time.time(),
        "level":   level,
        "message": message,
        "source":  source,
    }


# ──────────────────────────────────────────────────
# ServicesManager
# ──────────────────────────────────────────────────

class ServicesManager:
    """
    Controls mac_api and docker-compose sub-processes and monitors
    the MySQL connection health.
    """

    # Commands
    # Commands — sys.executable ensures the venv's Python is used
    MAC_API_CMD     = [sys.executable, "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
    DOCKER_UP_CMD   = ["docker-compose", "up", "-d"]
    DOCKER_DOWN_CMD = ["docker-compose", "down"]

    # Health-check intervals (seconds)
    DB_CHECK_INTERVAL      = 10
    MAC_API_CHECK_INTERVAL = 5
    MAC_API_HEALTH_URL     = "http://127.0.0.1:8000/health"

    def __init__(
        self,
        on_status_changed: StatusChangedCallback,
        on_service_log: ServiceLogCallback,
        work_dir: str = ".",
    ) -> None:
        self._on_status_changed = on_status_changed
        self._on_service_log    = on_service_log
        self._work_dir          = work_dir

        self._status   = ServicesStatus()
        self._lock     = threading.Lock()

        # Live sub-process handles
        self._mac_api_proc: Optional[subprocess.Popen] = None
        self._docker_proc:  Optional[subprocess.Popen] = None

        # Health-check threads
        self._db_thread = threading.Thread(
            target=self._db_health_loop, name="DBHealthCheck", daemon=True
        )
        self._mac_api_health_thread = threading.Thread(
            target=self._mac_api_health_loop, name="MacApiHealthCheck", daemon=True
        )

    # ── public API ────────────────────────────────

    def start(self) -> None:
        """Start background threads (does NOT auto-start services)."""
        self._db_thread.start()
        self._mac_api_health_thread.start()
        logger.info("ServicesManager started")

    def get_status(self) -> dict:
        with self._lock:
            return self._status.to_dict()

    # ── mac_api actions ───────────────────────────

    def mac_api_start(self) -> None:
        threading.Thread(target=self._mac_api_do_start, daemon=True).start()

    def mac_api_stop(self) -> None:
        threading.Thread(target=self._mac_api_do_stop, daemon=True).start()

    def mac_api_restart(self) -> None:
        threading.Thread(target=self._mac_api_do_restart, daemon=True).start()

    # ── docker actions ────────────────────────────

    def docker_start(self) -> None:
        threading.Thread(target=self._docker_do_start, daemon=True).start()

    def docker_stop(self) -> None:
        threading.Thread(target=self._docker_do_stop, daemon=True).start()

    def docker_restart(self) -> None:
        threading.Thread(target=self._docker_do_restart, daemon=True).start()

    # ──────────────────────────────────────────────
    # mac_api internals
    # ──────────────────────────────────────────────

    def _mac_api_do_start(self) -> None:
        with self._lock:
            if self._status.mac_api in ("running", "starting"):
                return
            self._status.mac_api = "starting"
        self._emit_status()
        self._log("info", "Starting mac_api…", "mac_api")

        try:
            proc = subprocess.Popen(
                self.MAC_API_CMD,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                cwd=_BACKEND_DIR,
            )
            self._mac_api_proc = proc
            with self._lock:
                self._status.mac_api = "running"
            self._emit_status()
            self._log("info", f"mac_api started (PID {proc.pid})", "mac_api")

            # Stream stdout in a background thread
            threading.Thread(
                target=self._stream_output,
                args=(proc, "mac_api"),
                daemon=True,
            ).start()

        except Exception:
            err = traceback.format_exc()
            logger.error("Failed to start mac_api:\n%s", err)
            self._log("error", f"Failed to start mac_api: {err}", "mac_api")
            with self._lock:
                self._status.mac_api = "stopped"
            self._emit_status()

    def _mac_api_do_stop(self) -> None:
        with self._lock:
            if self._status.mac_api in ("stopped", "stopping"):
                return
            self._status.mac_api = "stopping"
        self._emit_status()
        self._log("info", "Stopping mac_api…", "mac_api")

        try:
            if self._mac_api_proc and self._mac_api_proc.poll() is None:
                self._mac_api_proc.terminate()
                self._mac_api_proc.wait(timeout=10)
        except Exception:
            logger.error("Error stopping mac_api:\n%s", traceback.format_exc())
            if self._mac_api_proc:
                self._mac_api_proc.kill()
        finally:
            self._mac_api_proc = None
            with self._lock:
                self._status.mac_api = "stopped"
            self._emit_status()
            self._log("info", "mac_api stopped", "mac_api")

    def _mac_api_do_restart(self) -> None:
        with self._lock:
            self._status.mac_api = "restarting"
        self._emit_status()
        self._log("info", "Restarting mac_api…", "mac_api")
        self._mac_api_do_stop()
        time.sleep(1)
        self._mac_api_do_start()

    # ──────────────────────────────────────────────
    # docker internals
    # ──────────────────────────────────────────────

    def _docker_do_start(self) -> None:
        with self._lock:
            if self._status.docker in ("running", "starting"):
                return
            self._status.docker = "starting"
        self._emit_status()
        self._log("info", "Starting Docker Compose…", "docker")

        try:
            result = subprocess.run(
                self.DOCKER_UP_CMD,
                capture_output=True,
                text=True,
                cwd=self._work_dir,
            )
            if result.returncode == 0:
                with self._lock:
                    self._status.docker = "running"
                self._emit_status()
                self._log("info", "Docker Compose started", "docker")
                for line in (result.stdout + result.stderr).splitlines():
                    if line.strip():
                        self._log("debug", line, "docker")
            else:
                raise RuntimeError(result.stderr or "docker-compose up failed")

        except Exception:
            err = traceback.format_exc()
            logger.error("Failed to start Docker:\n%s", err)
            self._log("error", f"Failed to start Docker: {err}", "docker")
            with self._lock:
                self._status.docker = "stopped"
            self._emit_status()

    def _docker_do_stop(self) -> None:
        with self._lock:
            if self._status.docker in ("stopped", "stopping"):
                return
            self._status.docker = "stopping"
        self._emit_status()
        self._log("info", "Stopping Docker Compose…", "docker")

        try:
            result = subprocess.run(
                self.DOCKER_DOWN_CMD,
                capture_output=True,
                text=True,
                cwd=self._work_dir,
            )
            for line in (result.stdout + result.stderr).splitlines():
                if line.strip():
                    self._log("debug", line, "docker")
        except Exception:
            logger.error("Error stopping Docker:\n%s", traceback.format_exc())
        finally:
            with self._lock:
                self._status.docker = "stopped"
            self._emit_status()
            self._log("info", "Docker Compose stopped", "docker")

    def _docker_do_restart(self) -> None:
        with self._lock:
            self._status.docker = "restarting"
        self._emit_status()
        self._log("info", "Restarting Docker Compose…", "docker")
        self._docker_do_stop()
        time.sleep(2)
        self._docker_do_start()

    # ──────────────────────────────────────────────
    # DB health-check
    # ──────────────────────────────────────────────

    def _db_health_loop(self) -> None:
        while True:
            self._check_db()
            time.sleep(self.DB_CHECK_INTERVAL)

    def _mac_api_health_loop(self) -> None:
        while True:
            self._check_mac_api_health()
            time.sleep(self.MAC_API_CHECK_INTERVAL)

    def _check_mac_api_health(self) -> None:
        import urllib.request
        import urllib.error
        try:
            with urllib.request.urlopen(self.MAC_API_HEALTH_URL, timeout=3) as resp:
                healthy = resp.status == 200
        except Exception:
            healthy = False

        new_health: ApiHealthState = "up" if healthy else "down"
        with self._lock:
            if self._status.mac_api_health != new_health:
                self._status.mac_api_health = new_health
                changed = True
            else:
                changed = False
        if changed:
            self._emit_status()

    def _check_db(self) -> None:
        with self._lock:
            self._status.db_connection = "checking"
        self._emit_status()

        connected = False
        try:
            import socket as _socket
            sock = _socket.create_connection(("127.0.0.1", 3307), timeout=3)
            sock.close()
            connected = True
        except Exception:
            connected = False

        with self._lock:
            self._status.db_connection = "connected" if connected else "disconnected"
        self._emit_status()

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _emit_status(self) -> None:
        try:
            self._on_status_changed(self.get_status())
        except Exception:
            logger.error("Exception in status callback:\n%s", traceback.format_exc())

    def _log(self, level: str, message: str, source: ServiceSource) -> None:
        try:
            self._on_service_log(_make_log_entry(level, message, source))
        except Exception:
            pass

    def _stream_output(self, proc: subprocess.Popen, source: ServiceSource) -> None:
        """Stream stdout lines of a sub-process to the service log."""
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._log("debug", line, source)
            # Process exited
            rc = proc.wait()
            if rc != 0:
                self._log("warning", f"Process exited with code {rc}", source)
                with self._lock:
                    if source == "mac_api":
                        self._status.mac_api = "stopped"
                self._emit_status()
        except Exception:
            logger.error("Error streaming output for %s:\n%s", source, traceback.format_exc())
