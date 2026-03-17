"""
monitor.py — Business logic for the Verdin AM62 Flash Monitor.

Responsibilities:
  - SerialListener : TCP server that receives board serial numbers from prepare.sh
  - NginxMonitor   : Tails the NGINX access log and tracks file-download progress
  - ModuleStore    : Thread-safe state store for all active board modules

The two monitors call `on_modules_changed(snapshot)` whenever the state changes,
so the Flask-SocketIO layer can push updates to connected clients.
"""

from __future__ import annotations

import logging
import re
import socket
import subprocess
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

# ──────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────

NGINX_LOG_PATH = "/var/log/nginx/access.log"
TCP_HOST       = "0.0.0.0"
TCP_PORT       = 5000

# Keys are substrings matched against each NGINX log line.
# Values are the progress points awarded for that file download.
FILE_PROGRESS: Dict[str, int] = {
    "bootfs.tar.xz": 20,
    ".tar.xz HTTP":  60,
    "tiboot3":        5,
    "tispl":          5,
    "u-boot.img":    10,   # bumped to 10 so the total reaches 100
}

STEP_ORDER = list(FILE_PROGRESS.keys())   # used to determine currentStep

logger = logging.getLogger("FlashBench.Monitor")

# ──────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────

BoardStatus = str   # 'waiting' | 'flashing' | 'done' | 'error'


@dataclass
class BoardModule:
    serial:       str
    progress:     int              = 0
    status:       BoardStatus      = "waiting"
    current_step: Optional[str]    = None
    start_time:   Optional[float]  = None   # Unix timestamp (seconds)

    def to_dict(self) -> dict:
        return {
            "serial":      self.serial,
            "progress":    self.progress,
            "status":      self.status,
            "currentStep": self.current_step,
            "startTime":   self.start_time,
        }


# ──────────────────────────────────────────────────
# Thread-safe module store
# ──────────────────────────────────────────────────

ModulesChangedCallback = Callable[[dict], None]


class ModuleStore:
    """Central, thread-safe registry of all boards being monitored."""

    def __init__(self) -> None:
        self._modules: Dict[str, BoardModule] = {}
        self._lock = threading.Lock()
        self._callbacks: list[ModulesChangedCallback] = []

    # ── subscription ──────────────────────────────

    def subscribe(self, cb: ModulesChangedCallback) -> None:
        """Register a callback invoked (without the lock held) on every state change."""
        self._callbacks.append(cb)

    def _notify(self) -> None:
        snapshot = self.snapshot()
        for cb in self._callbacks:
            try:
                cb(snapshot)
            except Exception:
                logger.error("Exception in ModuleStore subscriber:\n%s", traceback.format_exc())

    # ── mutations ─────────────────────────────────

    def register_board(self, ip: str, serial: str) -> None:
        """Called by SerialListener when a board announces itself."""
        with self._lock:
            if ip not in self._modules:
                self._modules[ip] = BoardModule(serial=serial)
                logger.info("Board registered | serial=%s | ip=%s", serial, ip)
            else:
                # Board reconnected — reset its state
                mod = self._modules[ip]
                mod.serial       = serial
                mod.progress     = 0
                mod.status       = "waiting"
                mod.current_step = None
                mod.start_time   = None
                logger.info("Board re-registered (reset) | serial=%s | ip=%s", serial, ip)
        self._notify()

    def apply_progress(self, ip: str, step_key: str, points: int) -> None:
        """Called by NginxMonitor when a file download is detected for an IP."""
        with self._lock:
            if ip not in self._modules:
                # Unknown board — create a placeholder
                self._modules[ip] = BoardModule(serial="unknown")
                logger.warning("Progress received for unregistered IP %s — created placeholder", ip)

            mod = self._modules[ip]

            # First hit → start the flash
            if mod.status == "waiting":
                mod.status     = "flashing"
                mod.start_time = time.time()

            mod.current_step = step_key
            mod.progress    += points
            if mod.progress >= 100:
                mod.progress  = 100
                mod.status    = "done"

            logger.info(
                "Progress update | serial=%s | ip=%s | step=%s | progress=%d%%",
                mod.serial, ip, step_key, mod.progress,
            )
        self._notify()

    def handle_event(self, ip: str, raw_data: str) -> None:
        """
        Called by SerialListener when the received data looks like a
        pipe-delimited traceability/post-flash event rather than a plain
        serial number.  We do NOT reset the board state here.
        Instead, TRACEABILITY_OK and END/Rebooting promote the board to
        'done' so the card turns green.
        """
        with self._lock:
            if ip not in self._modules:
                # Board not yet known — ignore orphaned events
                logger.warning("Event received for unknown IP %s — ignored", ip)
                return

            mod = self._modules[ip]

            if "TRACEABILITY_OK" in raw_data or ("END" in raw_data and "Rebooting" in raw_data):
                mod.status   = "done"
                mod.progress = 100
                logger.info(
                    "Board flash confirmed done | serial=%s | ip=%s | event=%s",
                    mod.serial, ip, raw_data.strip(),
                )
            else:
                logger.info(
                    "Board event | serial=%s | ip=%s | event=%s",
                    mod.serial, ip, raw_data.strip(),
                )
        self._notify()

    def mark_error(self, ip: str, message: str = "") -> None:
        with self._lock:
            if ip in self._modules:
                self._modules[ip].status = "error"
                logger.error("Board error | ip=%s | %s", ip, message)
        self._notify()
    def clear_done(self) -> None:
        """Remove all boards whose status is 'done' (or 'error')."""
        with self._lock:
            to_remove = [ip for ip, mod in self._modules.items() if mod.status in ("done", "error")]
            for ip in to_remove:
                del self._modules[ip]
            if to_remove:
                logger.info("Cleared %d finished board(s): %s", len(to_remove), ", ".join(to_remove))
        if to_remove:
            self._notify()

    def clear_all(self) -> None:
        """Remove all boards from the store."""
        with self._lock:
            count = len(self._modules)
            self._modules.clear()
            logger.info("Cleared all %d board(s) from store", count)
        self._notify()
    # ── read ──────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a JSON-serialisable copy of the current state."""
        with self._lock:
            return {ip: mod.to_dict() for ip, mod in self._modules.items()}


# ──────────────────────────────────────────────────
# TCP listener (receives serial numbers from boards)
# ──────────────────────────────────────────────────

class SerialListener:
    """
    Listens on TCP_PORT for incoming board announcements.
    Each board sends its serial number as a plain UTF-8 string.

    The internal watchdog loop automatically restarts the TCP server
    whenever it crashes, using exponential back-off (max 60 s).
    """

    # Status values: 'starting' | 'running' | 'error' | 'restarting'
    RETRY_BASE_DELAY = 2      # seconds before first retry
    RETRY_MAX_DELAY  = 60     # cap for exponential back-off

    def __init__(
        self,
        store: ModuleStore,
        host: str = TCP_HOST,
        port: int = TCP_PORT,
        on_status_changed: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.store   = store
        self.host    = host
        self.port    = port
        self._on_status_changed = on_status_changed

        self._status:      str           = "starting"
        self._last_error:  str           = ""
        self._retry_count: int           = 0
        self._lock                       = threading.Lock()

        self._thread = threading.Thread(
            target=self._watchdog, name="SerialListener", daemon=True
        )

    # ── public API ────────────────────────────────

    def start(self) -> None:
        self._thread.start()
        logger.info("SerialListener watchdog started — will bind on %s:%d", self.host, self.port)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "status":      self._status,
                "last_error":  self._last_error,
                "retry_count": self._retry_count,
                "host":        self.host,
                "port":        self.port,
            }

    # ── internal ──────────────────────────────────

    def _set_status(self, status: str, error: str = "") -> None:
        with self._lock:
            self._status     = status
            self._last_error = error
        logger.info("SerialListener status → %s%s", status, f" | {error}" if error else "")
        if self._on_status_changed:
            try:
                self._on_status_changed(status)
            except Exception:
                pass

    def _watchdog(self) -> None:
        """
        Outer retry loop: (re-)starts the TCP server on any failure.
        Uses exponential back-off up to RETRY_MAX_DELAY seconds.
        """
        delay = self.RETRY_BASE_DELAY
        while True:
            try:
                self._set_status("starting")
                self._serve()
                # _serve() normally blocks forever; reaching here means clean exit
                break
            except Exception:
                err = traceback.format_exc()
                self._retry_count += 1
                self._set_status("error", err.splitlines()[-1])
                logger.error(
                    "SerialListener crashed (retry #%d, next attempt in %ds):\n%s",
                    self._retry_count, delay, err,
                )
                time.sleep(delay)
                delay = min(delay * 2, self.RETRY_MAX_DELAY)
                self._set_status("restarting")

    def _serve(self) -> None:
        """Inner TCP accept loop — runs until an exception escapes."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.host, self.port))
            srv.listen()
            self._set_status("running")
            logger.info("SerialListener waiting for connections on port %d", self.port)

            while True:
                conn, addr = srv.accept()
                threading.Thread(
                    target=self._handle_client,
                    args=(conn, addr),
                    daemon=True,
                ).start()

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
        with conn:
            try:
                data = conn.recv(1024).decode("utf-8", errors="replace").strip()
                if data:
                    if "|" in data:
                        # Pipe-delimited traceability / post-flash event
                        self.store.handle_event(ip=addr[0], raw_data=data)
                    else:
                        # Plain serial number — new board or board reset
                        self.store.register_board(ip=addr[0], serial=data)
            except Exception:
                logger.error(
                    "Exception handling client %s:\n%s", addr[0], traceback.format_exc()
                )


# ──────────────────────────────────────────────────
# NGINX log monitor
# ──────────────────────────────────────────────────

class NginxMonitor:
    """
    Tails the NGINX access log and, for each line, checks whether it
    corresponds to a known file download.  When a match is found the
    progress of the originating board is updated in the store.
    """

    def __init__(self, store: ModuleStore, log_path: str = NGINX_LOG_PATH) -> None:
        self.store    = store
        self.log_path = log_path
        self._thread  = threading.Thread(target=self._run, name="NginxMonitor", daemon=True)

    def start(self) -> None:
        self._thread.start()
        logger.info("NginxMonitor started — watching %s", self.log_path)

    def _run(self) -> None:
        try:
            process = subprocess.Popen(
                ["sudo", "tail", "-F", self.log_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            logger.info("NginxMonitor: tail process PID=%d", process.pid)

            for line in process.stdout:
                self._process_line(line)

        except Exception:
            logger.error("Fatal exception in NginxMonitor:\n%s", traceback.format_exc())

    _IP_RE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3})")

    def _process_line(self, line: str) -> None:
        match = self._IP_RE.match(line)
        if not match:
            return
        ip = match.group(1)

        for key, points in FILE_PROGRESS.items():
            if key in line:
                self.store.apply_progress(ip, key, points)
                break   # only award the first matching key per line
