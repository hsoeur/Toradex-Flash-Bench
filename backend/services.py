"""
services.py — Passive monitoring of external services.

Monitored items:
  - db_connection  : TCP reachability of MySQL on 127.0.0.1:3306
  - dnsmasq_status : systemd unit status
  - nginx_status   : systemd unit status

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
import time
import threading
import traceback
from typing import Callable, Literal

logger = logging.getLogger("FlashBench.Services")

# ──────────────────────────────────────────────────
# Types
# ──────────────────────────────────────────────────

DbState             = Literal["connected", "disconnected", "checking"]
SystemdServiceState = Literal["active", "inactive", "unknown"]

StatusChangedCallback = Callable[[dict], None]
ServiceLogCallback    = Callable[[dict], None]   # {ts, level, message, source}


# ──────────────────────────────────────────────────
# Status container
# ──────────────────────────────────────────────────

class ServicesStatus:
    def __init__(self) -> None:
        self.db_connection:  DbState             = "disconnected"
        self.dnsmasq_status: SystemdServiceState = "unknown"
        self.nginx_status:   SystemdServiceState = "unknown"

    def to_dict(self) -> dict:
        return {
            "db_connection":  self.db_connection,
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
    Monitors the MySQL DB connection and systemd services.
    Does not manage any processes — read-only / passive.
    """

    DB_HOST            = "127.0.0.1"
    DB_PORT            = 3306
    DB_CHECK_INTERVAL  = 10   # seconds

    SYSTEMD_CHECK_INTERVAL = 10   # seconds

    def __init__(
        self,
        on_status_changed: StatusChangedCallback,
        on_service_log: ServiceLogCallback,
    ) -> None:
        self._on_status_changed = on_status_changed
        self._on_service_log    = on_service_log

        self._status = ServicesStatus()
        self._lock   = threading.Lock()

        self._db_thread = threading.Thread(
            target=self._db_health_loop, name="DBHealthCheck", daemon=True
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
        """Start background monitoring threads."""
        self._db_thread.start()
        self._dnsmasq_thread.start()
        self._nginx_thread.start()
        self._dnsmasq_log_thread.start()
        self._nginx_log_thread.start()
        logger.info("ServicesManager monitoring started")

    def get_status(self) -> dict:
        with self._lock:
            return self._status.to_dict()

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
