"""
services.py — Passive monitoring of external services.

Monitored items:
  - db_connection  : TCP reachability of MySQL on 127.0.0.1:3307
  - mac_api_health : HTTP /health endpoint of the MAC API on port 8000

This module does NOT start or stop any services — that is the responsibility
of an external tool.

Usage:
    mgr = ServicesManager(on_status_changed=my_callback, on_service_log=log_cb)
    mgr.start()   # starts background monitoring threads
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
import threading
import traceback
from typing import Callable, Literal, Optional

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger("FlashBench.Services")

# ──────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────

DbState             = Literal["connected", "disconnected", "checking"]
ApiHealthState      = Literal["up", "down", "unknown"]
MacApiState         = Literal["running", "stopped", "starting", "stopping", "restarting"]
SystemdServiceState = Literal["active", "inactive", "unknown"]

StatusChangedCallback = Callable[[dict], None]
ServiceLogCallback    = Callable[[dict], None]   # {ts, level, message, source}


# ──────────────────────────────────────────────────
# Status container
# ──────────────────────────────────────────────────

class ServicesStatus:
    def __init__(self) -> None:
        self.mac_api:        MacApiState         = "stopped"
        self.db_connection:  DbState             = "disconnected"
        self.mac_api_health: ApiHealthState      = "unknown"
        self.dnsmasq_status: SystemdServiceState = "unknown"
        self.nginx_status:   SystemdServiceState = "unknown"

    def to_dict(self) -> dict:
        return {
            "mac_api":        self.mac_api,
            "db_connection":  self.db_connection,
            "mac_api_health": self.mac_api_health,
            "dnsmasq_status": self.dnsmasq_status,
            "nginx_status":   self.nginx_status,
        }


# ──────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────

def _make_log_entry(level: str, message: str, source: str) -> dict:
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
    Monitors the MySQL DB connection and the MAC API health endpoint.
    Does not manage any processes — read-only / passive.
    """

    DB_HOST            = "127.0.0.1"
    DB_PORT            = 3307
    DB_CHECK_INTERVAL  = 10   # seconds

    MAC_API_HEALTH_URL     = "http://127.0.0.1:8000/health"
    MAC_API_CHECK_INTERVAL = 5    # seconds

    SYSTEMD_CHECK_INTERVAL = 10   # seconds

    MAC_API_CMD = [sys.executable, "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

    def __init__(
        self,
        on_status_changed: StatusChangedCallback,
        on_service_log: ServiceLogCallback,
    ) -> None:
        self._on_status_changed = on_status_changed
        self._on_service_log    = on_service_log

        self._status = ServicesStatus()
        self._lock   = threading.Lock()

        self._mac_api_proc: Optional[subprocess.Popen] = None

        self._db_thread = threading.Thread(
            target=self._db_health_loop, name="DBHealthCheck", daemon=True
        )
        self._mac_api_thread = threading.Thread(
            target=self._mac_api_health_loop, name="MacApiHealthCheck", daemon=True
        )
        self._dnsmasq_thread = threading.Thread(
            target=self._dnsmasq_health_loop, name="DnsmasqHealthCheck", daemon=True
        )
        self._nginx_thread = threading.Thread(
            target=self._nginx_health_loop, name="NginxHealthCheck", daemon=True
        )
        self._dnsmasq_log_thread = threading.Thread(
            target=self._dnsmasq_log_stream_loop, name="DnsmasqLogStream", daemon=True
        )
        self._nginx_log_thread = threading.Thread(
            target=self._nginx_log_stream_loop, name="NginxLogStream", daemon=True
        )

    # ── Public API ────────────────────────────────

    def start(self) -> None:
        """Start background monitoring threads and auto-start the MAC API."""
        self._db_thread.start()
        self._mac_api_thread.start()
        self._dnsmasq_thread.start()
        self._nginx_thread.start()
        self._dnsmasq_log_thread.start()
        self._nginx_log_thread.start()
        logger.info("ServicesManager monitoring started")
        self.mac_api_start()

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

    # ── mac_api internals ─────────────────────────

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
            threading.Thread(
                target=self._stream_mac_api_output,
                args=(proc,),
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

    def _stream_mac_api_output(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self._log("debug", line, "mac_api")
            rc = proc.wait()
            if rc != 0:
                self._log("warning", f"mac_api exited with code {rc}", "mac_api")
            with self._lock:
                self._status.mac_api = "stopped"
            self._emit_status()
        except Exception:
            logger.error("Error streaming mac_api output:\n%s", traceback.format_exc())

    # ── DB monitoring ─────────────────────────────

    def _db_health_loop(self) -> None:
        while True:
            self._check_db()
            time.sleep(self.DB_CHECK_INTERVAL)

    def _check_db(self) -> None:
        with self._lock:
            self._status.db_connection = "checking"
        self._emit_status()

        try:
            import socket as _socket
            sock = _socket.create_connection((self.DB_HOST, self.DB_PORT), timeout=3)
            sock.close()
            connected = True
        except Exception:
            connected = False

        new_state: DbState = "connected" if connected else "disconnected"
        with self._lock:
            self._status.db_connection = new_state
        self._emit_status()

        level = "info" if connected else "warning"
        self._log(level, f"DB {new_state} ({self.DB_HOST}:{self.DB_PORT})", "db")

    # ── MAC API health monitoring ──────────────────

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
            changed = self._status.mac_api_health != new_health
            self._status.mac_api_health = new_health
        if changed:
            self._emit_status()

    # ── dnsmasq (DHCP/DNS) monitoring ─────────────

    def _dnsmasq_health_loop(self) -> None:
        while True:
            self._check_systemd_service("dnsmasq", "dnsmasq_status", "dhcp")
            time.sleep(self.SYSTEMD_CHECK_INTERVAL)

    # ── nginx monitoring ───────────────────────────

    def _nginx_health_loop(self) -> None:
        while True:
            self._check_systemd_service("nginx", "nginx_status", "nginx")
            time.sleep(self.SYSTEMD_CHECK_INTERVAL)

    def _check_systemd_service(self, service: str, status_attr: str, log_source: str) -> None:
        """Run 'systemctl is-active <service>' and update the matching status field."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                timeout=5,
            )
            output = result.stdout.strip()
            new_state: SystemdServiceState = "active" if output == "active" else "inactive"
        except Exception:
            new_state = "unknown"

        with self._lock:
            changed = getattr(self._status, status_attr) != new_state
            setattr(self._status, status_attr, new_state)
        if changed:
            self._emit_status()

    # ── dnsmasq / nginx log streaming ─────────────────────────────

    def _dnsmasq_log_stream_loop(self) -> None:
        self._stream_command_logs(
            cmd=["sudo", "journalctl", "-u", "dnsmasq", "-f", "--no-pager", "-n", "50", "-o", "short"],
            source="dhcp",
        )

    def _nginx_log_stream_loop(self) -> None:
        self._stream_command_logs(
            cmd=["sudo", "tail", "-n", "50", "-f", "/var/log/nginx/access.log"],
            source="nginx",
        )

    def _stream_command_logs(self, cmd: list, source: str) -> None:
        """
        Runs *cmd* and emits each output line as a log entry for *source*.
        Automatically restarts after a 5-second pause when the process exits.
        """
        while True:
            try:
                self._log("info", f"Démarrage du flux : {' '.join(cmd)}", source)
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                for raw in proc.stdout:
                    line = raw.rstrip()
                    if line:
                        self._log("info", line, source)
                rc = proc.wait()
                self._log("warning", f"Flux terminé (code {rc}), redémarrage dans 5 s…", source)
            except Exception:
                self._log("error", f"Erreur flux ({source}): {traceback.format_exc()}", source)
            time.sleep(5)

    # ── Helpers ───────────────────────────────────

    def _emit_status(self) -> None:
        try:
            self._on_status_changed(self.get_status())
        except Exception:
            logger.error("Exception in status callback:\n%s", traceback.format_exc())

    def _log(self, level: str, message: str, source: str) -> None:
        try:
            self._on_service_log(_make_log_entry(level, message, source))
        except Exception:
            pass
