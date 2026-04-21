"""
monitor.py — Business logic for the Verdin AM62 Flash Monitor.

Responsibilities
~~~~~~~~~~~~~~~~
- ``BoardModule``   : Data model for a single board being flashed.
- ``BoardStatus``   : Enum of the possible board lifecycle states.
- ``ModuleStore``   : Thread-safe state store for all active board modules.
- ``SerialListener``: TCP server that receives serial numbers / events from prepare.sh.

Both monitors call registered ``ModulesChangedCallback`` subscribers whenever
the state mutates so the Flask-SocketIO layer can push updates to clients.
"""

from __future__ import annotations

__all__ = [
    "BoardModule",
    "BoardStatus",
    "ModuleStore",
    "ModulesChangedCallback",
    "SerialListener",
]

import logging
import re
import socket
import subprocess
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict

from config import SERIAL_TCP_HOST, SERIAL_TCP_PORT

logger = logging.getLogger("FlashBench.Monitor")


# ──────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────


class BoardStatus(str, Enum):
    """
    Lifecycle states for a board module.

    Inherits from ``str`` so that ``json.dumps`` / SocketIO emit produce
    plain string values without needing a custom encoder.
    """

    WAITING  = "waiting"
    FLASHING = "flashing"
    DONE     = "done"
    ERROR    = "error"


# Duration (seconds) during which an IP is suppressed after being cleared.
# This prevents stale TCP re-registrations from an old board that was removed.
IP_SUPPRESSION_TIMEOUT = 30


@dataclass(slots=True)
class BoardModule:
    """Represents a single board being monitored during a flash session."""

    serial:          str
    status:          BoardStatus      = BoardStatus.WAITING
    start_time:      float | None     = None    # Unix timestamp (seconds)
    error_message:   str | None       = None    # Set when status == ERROR
    registered_at:   float            = 0.0     # Unix timestamp when board was registered

    # ── helpers ───────────────────────────────────

    def reset(self, serial: str) -> None:
        """Reinitialise mutable fields (board reconnected)."""
        self.serial          = serial
        self.status          = BoardStatus.WAITING
        self.start_time      = None
        self.error_message   = None
        self.registered_at   = time.time()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable snapshot (camelCase keys for the frontend)."""
        return {
            "serial":       self.serial,
            "status":       self.status.value,
            "startTime":    self.start_time,
            "errorMessage": self.error_message,
            "registeredAt": self.registered_at,
        }


# ──────────────────────────────────────────────────
# Thread-safe module store
# ──────────────────────────────────────────────────

ModulesChangedCallback = Callable[[dict], None]


class ModuleStore:
    """Central, thread-safe registry of all boards being monitored."""

    def __init__(self) -> None:
        self._modules: dict[str, BoardModule] = {}
        self._lock = threading.Lock()
        self._callbacks: list[ModulesChangedCallback] = []
        # IP suppression: maps IP → expiry timestamp.
        # Boards from suppressed IPs are silently rejected to prevent
        # stale serial numbers from re-appearing after a slot is cleared.
        self._suppressed_ips: Dict[str, float] = {}

    # ── subscription ──────────────────────────────

    def subscribe(self, cb: ModulesChangedCallback) -> None:
        """Register a callback invoked (without the lock held) on every state change."""
        self._callbacks.append(cb)

    def _notify(self) -> None:
        """Take a snapshot then fan-out to subscribers outside the lock."""
        snapshot = self.snapshot()
        for cb in self._callbacks:
            try:
                cb(snapshot)
            except Exception:
                logger.error("Exception in ModuleStore subscriber:\n%s", traceback.format_exc())

    # ── mutations ─────────────────────────────────

    def _is_suppressed(self, ip: str) -> bool:
        """Check if *ip* is currently suppressed (cleared recently)."""
        expiry = self._suppressed_ips.get(ip)
        if expiry is None:
            return False
        if time.time() < expiry:
            return True
        # Suppression expired — clean up
        del self._suppressed_ips[ip]
        return False

    def _suppress_ip(self, ip: str) -> None:
        """Mark *ip* as suppressed for ``IP_SUPPRESSION_TIMEOUT`` seconds."""
        self._suppressed_ips[ip] = time.time() + IP_SUPPRESSION_TIMEOUT
        logger.info(
            "IP %s suppressed for %ds to prevent stale re-registration",
            ip, IP_SUPPRESSION_TIMEOUT,
        )

    def unsuppress_ip(self, ip: str) -> None:
        """Explicitly remove IP suppression (e.g. operator intentionally re-uses the slot)."""
        with self._lock:
            removed = self._suppressed_ips.pop(ip, None)
            if removed:
                logger.info("IP %s suppression lifted manually", ip)

    def register_board(self, ip: str, serial: str) -> None:
        """Called by ``SerialListener`` when a board announces itself.

        Registration is **rejected** if the IP is currently suppressed
        (recently cleared from a slot) to prevent stale serial numbers
        from being re-assigned.
        """
        with self._lock:
            if self._is_suppressed(ip):
                logger.warning(
                    "BLOCKED stale registration | serial=%s | ip=%s "
                    "(IP suppressed after recent clear)",
                    serial, ip,
                )
                return

            if ip not in self._modules:
                self._modules[ip] = BoardModule(serial=serial, registered_at=time.time())
                logger.info("Board registered | serial=%s | ip=%s", serial, ip)
            else:
                self._modules[ip].reset(serial)
                logger.info("Board re-registered (reset) | serial=%s | ip=%s", serial, ip)
        self._notify()

    def handle_event(self, ip: str, raw_data: str) -> None:
        """
        Process a pipe-delimited traceability / post-flash event.

        Called by ``SerialListener`` when the received payload contains ``|``.
        Board state is **not** reset — only promoted or marked as error:

        - ``TRACEABILITY_OK`` or ``END … Rebooting`` → :attr:`BoardStatus.DONE`
        - ``ERROR`` → :attr:`BoardStatus.ERROR` with extracted detail

        Events from **suppressed** IPs are silently dropped.
        """
        with self._lock:
            if self._is_suppressed(ip):
                logger.warning(
                    "BLOCKED event from suppressed IP %s | data=%s",
                    ip, raw_data.strip(),
                )
                return

            if ip not in self._modules:
                logger.warning("Event received for unknown IP %s — ignored", ip)
                return

            mod = self._modules[ip]

            if "ERROR" in raw_data:
                error_detail = self._extract_error_detail(raw_data)
                mod.status        = BoardStatus.ERROR
                mod.error_message = error_detail
                logger.error(
                    "Board error detected | serial=%s | ip=%s | error=%s | raw=%s",
                    mod.serial, ip, error_detail, raw_data.strip(),
                )
            elif "TRACEABILITY_OK" in raw_data or ("END" in raw_data and "Rebooting" in raw_data):
                mod.status   = BoardStatus.DONE
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

    @staticmethod
    def _extract_error_detail(raw_data: str) -> str:
        """
        Parse a pipe-delimited log line from ``wrapup.sh`` and return the
        human-readable error description.

        Expected format::

            YYYY-MM-DD HH:MM:SS | ERROR | <detail> | key=value | …
        """
        parts = [p.strip() for p in raw_data.split("|")]
        for i, part in enumerate(parts):
            if "ERROR" in part:
                detail_parts = parts[i + 1:] if i + 1 < len(parts) else []
                return " | ".join(detail_parts) if detail_parts else "Unknown error"
        return raw_data.strip()

    def mark_done(self, ip: str) -> None:
        """Mark a board as successfully done (e.g. after traceability confirmation)."""
        with self._lock:
            if ip not in self._modules:
                logger.warning("mark_done called for unknown IP %s — ignored", ip)
                return
            mod = self._modules[ip]
            mod.status   = BoardStatus.DONE
            logger.info("Board marked done (traceability confirmed) | serial=%s | ip=%s", mod.serial, ip)
        self._notify()

    def mark_error(self, ip: str, message: str = "") -> None:
        """Mark a board as failed with an optional error *message*."""
        with self._lock:
            if ip not in self._modules:
                logger.warning("mark_error called for unknown IP %s — ignored", ip)
                return
            mod = self._modules[ip]
            mod.status        = BoardStatus.ERROR
            mod.error_message = message or "Unknown error"
            logger.error("Board error | ip=%s | %s", ip, message)
        self._notify()

    def clear_done(self) -> None:
        """Remove all boards whose status is ``DONE`` or ``ERROR``.

        Cleared IPs are suppressed to prevent stale re-registrations.
        """
        should_notify = False
        with self._lock:
            terminal = {BoardStatus.DONE, BoardStatus.ERROR}
            to_remove = [ip for ip, mod in self._modules.items() if mod.status in terminal]
            for ip in to_remove:
                del self._modules[ip]
                self._suppress_ip(ip)
            if to_remove:
                logger.info(
                    "Cleared %d finished board(s): %s (IPs suppressed)",
                    len(to_remove), ", ".join(to_remove),
                )
                should_notify = True
        if should_notify:
            self._notify()

    def clear_one(self, ip: str) -> None:
        """Remove a single board by *ip* from the store.

        The IP is also **suppressed** for ``IP_SUPPRESSION_TIMEOUT``
        seconds to prevent stale TCP re-registrations from the old board.
        """
        should_notify = False
        with self._lock:
            if ip in self._modules:
                serial = self._modules[ip].serial
                del self._modules[ip]
                self._suppress_ip(ip)
                logger.info(
                    "Cleared single board | ip=%s | serial=%s | IP suppressed",
                    ip, serial,
                )
                should_notify = True
            else:
                logger.warning("clear_one called for unknown IP %s — ignored", ip)
        if should_notify:
            self._notify()

    def clear_all(self) -> None:
        """Remove **all** boards from the store regardless of state.

        All current IPs are suppressed to prevent stale re-registrations.
        """
        with self._lock:
            for ip in self._modules:
                self._suppress_ip(ip)
            count = len(self._modules)
            self._modules.clear()
            logger.info("Cleared all %d board(s) from store (all IPs suppressed)", count)
        self._notify()

    # ── read ──────────────────────────────────────

    def snapshot(self) -> dict[str, dict]:
        """Return a JSON-serialisable copy of the current state."""
        with self._lock:
            return {ip: mod.to_dict() for ip, mod in self._modules.items()}


# ──────────────────────────────────────────────────
# TCP listener (receives serial numbers from boards)
# ──────────────────────────────────────────────────


class SerialListener:
    """
    TCP server that accepts board announcements on the configured port.

    Each board sends either:
    - a **plain serial number** (new board registration), or
    - a **pipe-delimited event** forwarded to :meth:`ModuleStore.handle_event`.

    An internal watchdog loop restarts the server on crashes using
    exponential back-off (capped at :attr:`RETRY_MAX_DELAY` seconds).
    """

    RETRY_BASE_DELAY: int = 2    # seconds before first retry
    RETRY_MAX_DELAY:  int = 60   # cap for exponential back-off

    def __init__(
        self,
        store: ModuleStore,
        host: str = SERIAL_TCP_HOST,
        port: int = SERIAL_TCP_PORT,
        on_status_changed: Callable[[str], None] | None = None,
    ) -> None:
        self._store  = store
        self._host   = host
        self._port   = port
        self._on_status_changed = on_status_changed

        self._status:      str = "starting"
        self._last_error:  str = ""
        self._retry_count: int = 0
        self._lock = threading.Lock()

        self._thread = threading.Thread(
            target=self._watchdog, name="SerialListener", daemon=True,
        )

    # ── public API ────────────────────────────────

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        """Start the watchdog thread (idempotent before the thread is joined)."""
        self._thread.start()
        logger.info("SerialListener watchdog started — will bind on %s:%d", self._host, self._port)

    def get_status(self) -> dict[str, object]:
        """Return a JSON-serialisable status dict."""
        with self._lock:
            return {
                "status":      self._status,
                "last_error":  self._last_error,
                "retry_count": self._retry_count,
                "host":        self._host,
                "port":        self._port,
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
                logger.debug("on_status_changed callback failed", exc_info=True)

    def _watchdog(self) -> None:
        """Outer retry loop with exponential back-off."""
        delay = self.RETRY_BASE_DELAY
        while True:
            try:
                self._set_status("starting")
                self._serve()
                break  # _serve() blocks forever; reaching here means clean exit
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
            srv.bind((self._host, self._port))
            srv.listen()
            self._set_status("running")
            logger.info("SerialListener awaiting connections on port %d", self._port)

            while True:
                conn, addr = srv.accept()
                threading.Thread(
                    target=self._handle_client,
                    args=(conn, addr),
                    daemon=True,
                ).start()

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
        """Process a single incoming TCP connection from a board."""
        with conn:
            try:
                data = conn.recv(1024).decode("utf-8", errors="replace").strip()
                if not data:
                    return
                if "|" in data:
                    self._store.handle_event(ip=addr[0], raw_data=data)
                else:
                    self._store.register_board(ip=addr[0], serial=data)
            except Exception:
                logger.error("Exception handling client %s:\n%s", addr[0], traceback.format_exc())
